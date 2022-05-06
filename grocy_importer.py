#!/usr/bin/python3

''' Help importing into Grocy '''

from __future__ import annotations

from argparse import ArgumentParser, FileType
import re
from email.parser import Parser
from typing import (Union, Iterable, Optional, TextIO, TypedDict, Literal,
                    Callable, cast, Any)
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import join
import sys
import json
from functools import partial

from bs4 import BeautifulSoup
import requests
from marshmallow import Schema, fields, EXCLUDE, post_load
from appdirs import user_config_dir


class UserError(Exception):
    ''' Exception that we display to the human '''


class AppConfigGrocySection(TypedDict):
    ''' [grocy]-section of our config.ini '''
    base_url: str
    api_key: str


class AppConfigPurchaseSection(TypedDict):
    ''' Common options for purchase-section of our config.ini

    e.g. [rewe] or [netto]
    '''
    shopping_location_id: int


class AppConfigRequired(TypedDict):
    ''' Structure of our config.ini '''
    grocy: AppConfigGrocySection


class AppConfig(AppConfigRequired, total=False):
    ''' Structure of our config.ini '''
    netto: AppConfigPurchaseSection
    rewe: AppConfigPurchaseSection


class GrocyProductBarCode(TypedDict):
    ''' A product barcode as returned from the Grocy API '''
    id: int
    product_id: int
    barcode: str
    qu_id: int
    amount: int
    shopping_location_id: int
    note: str


class GrocyProduct(TypedDict):
    ''' A product as returned from the Grocy API '''
    id: int
    name: str
    qu_factor_purchase_to_stock: float
    qu_id_stock: int
    product_group_id: int


class GrocyProductGroup(TypedDict):
    ''' A product group as returned from the Grocy API '''
    id: int
    name: str
    description: str


class GrocyShoppingLocation(TypedDict):
    ''' A shopping location as returned from the Grocy API '''
    id: int
    name: str


class GrocyQuantityUnit(TypedDict):
    ''' A quantity unit as returned from the Grocy API '''
    id: int
    name: str
    name_plural: str
    plural_forms: Optional[str]


class GrocyQUnitConvertion(TypedDict):
    ''' A quantity unit convertion as returned from the Grocy API '''
    id: int
    from_qu_id: int
    to_qu_id: int
    product_id: Optional[int]
    factor: float


class GrocyShoppingListItem(TypedDict):
    ''' A shopping list item as returned from the Grocy API '''
    id: int
    product_id: int
    note: Optional[str]
    amount: int
    shopping_list_id: int
    done: bool
    qu_id: int


class GrocyApi:
    ''' Calls to the Grocy REST-API '''

    def __init__(self, api_key: str, base_url: str, dry_run: bool):
        self.headers = {'GROCY-API-KEY': api_key}
        self.base_url = base_url
        self.dry_run = dry_run

    def get_all_product_barcodes(self) -> dict[str, GrocyProductBarCode]:
        ''' all product barcodes known to grocy '''
        response = requests.get(self.base_url + '/objects/product_barcodes',
                                headers=self.headers)
        return {p['barcode']: p for p in response.json()}

    def get_all_products(self) -> dict[str, GrocyProduct]:
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers)
        return {p['name']: p for p in response.json()}

    def get_all_products_by_id(self) -> dict[int, GrocyProduct]:
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers)
        return {p['id']: p for p in response.json()}

    def get_all_product_groups(self) -> dict[int, GrocyProductGroup]:
        ''' all product groups known to grocy '''
        response = requests.get(self.base_url + '/objects/product_groups',
                                headers=self.headers)
        return {p['id']: p for p in response.json()}

    def get_all_shopping_locations(self) -> Iterable[GrocyShoppingLocation]:
        ''' all shopping locations known to grocy '''
        response = requests.get(self.base_url + '/objects/shopping_locations',
                                headers=self.headers)
        return cast(Iterable[GrocyShoppingLocation], response.json())

    def get_all_quantity_units(self) -> Iterable[GrocyQuantityUnit]:
        ''' all quantity units known to grocy '''
        response = requests.get(self.base_url + '/objects/quantity_units',
                                headers=self.headers)
        return cast(Iterable[GrocyQuantityUnit], response.json())

    def get_all_quantity_units_by_id(self) -> dict[int, GrocyQuantityUnit]:
        ''' all quantity units known to grocy '''
        response = requests.get(self.base_url + '/objects/quantity_units',
                                headers=self.headers)
        return {p['id']: p for p in response.json()}

    def get_all_quantity_unit_convertions(self
                                          ) -> Iterable[GrocyQUnitConvertion]:
        ''' all quantity unit convertions known to grocy '''
        response = requests.get(self.base_url
                                + '/objects/quantity_unit_conversions',
                                headers=self.headers)
        return cast(Iterable[GrocyQUnitConvertion], response.json())

    def get_all_shopping_list(self) -> Iterable[GrocyShoppingListItem]:
        ''' all items on shopping lists '''
        response = requests.get(self.base_url
                                + '/objects/shopping_list',
                                headers=self.headers)
        return cast(Iterable[GrocyShoppingListItem], response.json())

    def purchase(self, product_id: int, amount: float, price: str,
                 shopping_location_id: int) -> None:
        ''' Add a purchase to grocy '''
        if self.dry_run:
            return
        call = f'/stock/products/{product_id}/add'
        response = requests.post(self.base_url + call,
                                 headers=self.headers,
                                 json={'amount': amount,
                                       'price': price,
                                       'transaction_type': 'purchase',
                                       'shopping_location_id':
                                       shopping_location_id
                                       })
        assert response.status_code//100 == 2


@dataclass
class AppArgs:
    ''' Structure of our CLI args '''
    dry_run: bool
    store: Literal['netto', 'rewe']
    file: TextIO
    func: Callable[[AppArgs, AppConfig, GrocyApi], None]
    order: int
    url: str


def normanlize_white_space(orig: str) -> str:
    ''' Remove multiple white space '''
    return re.sub(r'\s+', ' ', orig).strip()


@dataclass
class Purchase:
    ''' Represents a grocy purchase '''
    amount: Union[int, float]
    price: str
    name: str


def parse_purchase(args: list[str]) -> Purchase:
    ''' Parse a Netto store purchase '''
    return (Purchase(1,
                     from_netto_price(args[1]),
                     normanlize_white_space(args[0]))
            if len(args) == 2
            else Purchase(float(args[0].split()[0]),
                          from_netto_price(args[2]),
                          normanlize_white_space(args[1])))


def from_netto_price(netto_price: str) -> str:
    ''' convert from Netto store price format to grocy's '''
    return netto_price.split()[0].replace(',', '.')


def simplify(items: Iterable[Purchase]) -> list[Purchase]:
    '''
    >>> simplify([parse_purchase(['Milch', '1,00']),
    ... parse_purchase(['Mehl', '2,00'])])
    ... #doctest: +NORMALIZE_WHITESPACE
    [Purchase(amount=1, price='2.00', name='Mehl'),
     Purchase(amount=1, price='1.00', name='Milch')]

    >>> simplify([parse_purchase(['Milch', '1,00']),
    ... parse_purchase(['Milch', '1,00'])])
    [Purchase(amount=2, price='1.00', name='Milch')]
    >>> simplify([parse_purchase(['Milch', '1,00']),
    ... parse_purchase(['Mehl', '2,00']),
    ... parse_purchase(['Milch', '1,00'])])
    ... #doctest: +NORMALIZE_WHITESPACE
    [Purchase(amount=1, price='2.00', name='Mehl'),
     Purchase(amount=2, price='1.00', name='Milch')]
    >>> simplify([parse_purchase(['Punkte-Gutschein', '-1,05'])])
    []

    '''
    return [Purchase(sum(p.amount for p in g),
                     price,
                     name)
            for (name, price), g
            in groupby(sorted(items, key=lambda p: p.name),
                       lambda p: (p.name, p.price))
            if float(price) >= 0]


def rewe_purchase(args: AppArgs) -> list[Purchase]:
    ''' Import from REWE '''
    data = ReweJsonSchema.load_from_json_file(args.file)
    return [Purchase(line_item.quantity,
                     f"{line_item.total_price / 100:.2f}",
                     line_item.title)
            for line_item in data.sorted_orders()[args.order-1
                                                  ].sub_orders[0].line_items
            if line_item.title not in ['TimeSlot',
                                       'Enthaltene Pfandbeträge',
                                       'Getränke-Sperrgutaufschlag']]


def netto_purchase(args: AppArgs) -> list[Purchase]:
    ''' Import from Netto Marken-Discount

    Import a "digitaler Kassenbon" email from the German discount
    supermarket chain Netto Marken-Discount
    '''
    email = Parser().parse(args.file)
    html = list(part
                for part in email.walk()
                if part.get_content_type() == 'text/html'
                )[0].get_payload(decode=True)
    soup = BeautifulSoup(html, 'html5lib')
    purchase = list(column.get_text()
                    for row
                    in soup.select(' '.join(8*["tbody"] + ["tr"]))
                    if not list(row.select('td'))[0].get_text().endswith(':')
                    and not any(keyword in row.get_text()
                                for keyword in ['Filiale', 'Rabatt',
                                                'DeutschlandCard',
                                                'Punkte-Gutschein'])
                    for column in row.select('td')
                    if column.get_text() != ''
                    )
    items: list[list[str]] = []
    for pur in purchase:
        if pur.isspace():
            items.append([])
        else:
            items[-1].append(pur)
    return simplify(parse_purchase(item) for item in items if len(item) > 1)


@dataclass
class ReweJsonLineItem:
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    price: int
    quantity: int
    title: str
    total_price: int


@dataclass
class ReweJsonSuborder:
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    delivery_type: str
    # coupons: fields.List()
    # merchantInfo: object
    order_type: str
    payback_number: Optional[str]
    channel: str
    # deliveryAddress: object
    sub_order_value: int
    line_items: list[ReweJsonLineItem]
    # timeSlot: object
    additional_email: str
    user_comment: str
    merchant: str


@dataclass
class ReweJsonOrder:
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    # payments: fields.List()
    # invoiceAddress: object
    order_value: int
    client_info: str
    # paymentInfo: object
    sub_orders: list[ReweJsonSuborder]
    # OrderId: str
    creation_date: str


@dataclass
class ReweJsonOrdersList:
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    orders: list[ReweJsonOrder]


@dataclass
class ReweJson:
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    # addressData: fields.List()
    # deliveryflats: fields.List()
    # payback: object
    # customerData: object
    # paymentData: object
    orders: ReweJsonOrdersList
    # coupons: object

    def sorted_orders(self) -> list[ReweJsonOrder]:
        ''' Sort orders by creation_date '''
        return sorted(self.orders.orders,
                      key=lambda x: x.creation_date, reverse=True)

    def list_orders(self) -> Iterable[str]:
        ''' Format and sort orders for displaying to human '''
        for i, orde in enumerate(self.sorted_orders()):
            date = orde.creation_date
            value = orde.order_value
            merchant = orde.sub_orders[0].merchant
            yield(f'{i+1}. {date[:4]}-{date[4:6]}-{date[6:8]} {merchant}'
                  f' {int(value) / 100} €')


class ReweJsonLineItemSchema(Schema):
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    price = fields.Integer()
    quantity = fields.Integer()
    title = fields.Str()
    total_price = fields.Integer(data_key="totalPrice")

    @post_load
    def make(self, data: Any, **_: Any) -> ReweJsonLineItem:
        ''' Create instance from deserialized data '''
        return ReweJsonLineItem(**data)


class ReweJsonSuborderSchema(Schema):
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    delivery_type = fields.Str(data_key="deliveryType")
    # coupons = fields.List()
    # merchantInfo: object
    order_type = fields.Str(data_key="orderType")
    payback_number = fields.Str(allow_none=True, data_key="paybackNumber")
    channel = fields.Str()
    # deliveryAddress: object
    sub_order_value = fields.Integer(data_key="subOrderValue")
    line_items = fields.List(fields.Nested(ReweJsonLineItemSchema,
                                           unknown=EXCLUDE),
                             data_key="lineItems")
    # timeSlot: object
    additional_email = fields.Str(data_key="additionalEmail")
    user_comment = fields.Str(data_key="userComment")
    merchant = fields.Str()

    @post_load
    def make(self, data: Any, **_: Any) -> ReweJsonSuborder:
        ''' Create instance from deserialized data '''
        return ReweJsonSuborder(**data)


class ReweJsonOrderSchema(Schema):
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    # payments = fields.List()
    # invoiceAddress: object
    order_value = fields.Integer(data_key="orderValue")
    client_info = fields.Str(data_key="clientInfo")
    # paymentInfo: object
    sub_orders = fields.List(fields.Nested(ReweJsonSuborderSchema,
                                           unknown=EXCLUDE),
                             data_key="subOrders")
    # OrderId = fields.Str()
    creation_date = fields.Str(data_key="creationDate")

    @post_load
    def make(self, data: Any, **_: Any) -> ReweJsonOrder:
        ''' Create instance from deserialized data '''
        return ReweJsonOrder(**data)


class ReweJsonOrdersListSchema(Schema):
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    orders = fields.List(fields.Nested(ReweJsonOrderSchema, unknown=EXCLUDE))

    @post_load
    def make(self, data: Any, **_: Any) -> ReweJsonOrdersList:
        ''' Create instance from deserialized data '''
        return ReweJsonOrdersList(**data)


class ReweJsonSchema(Schema):
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    # addressData = fields.List()
    # deliveryflats = fields.List()
    # payback: object
    # customerData: object
    # paymentData: object
    orders = fields.Nested(ReweJsonOrdersListSchema, unknown=EXCLUDE)
    # coupons: object

    @staticmethod
    def load_from_json_file(file: TextIO) -> ReweJson:
        ''' Load data from given json file '''
        return cast(ReweJson,
                    ReweJsonSchema(unknown=EXCLUDE).load(json.load(file),
                                                         unknown=EXCLUDE))

    @post_load
    def make(self, data: Any, **_: Any) -> ReweJson:
        ''' Create instance from deserialized data '''
        return ReweJson(**data)


@dataclass
class UnparseableIngredient:
    ''' Represents an ingredient as listed in a recipe from the web. '''
    full: str


@dataclass
class Ingredient:
    ''' Represents an ingredient as listed in a recipe from the web. '''
    amount: str
    unit: str
    name: str
    full: str

    @staticmethod
    def parse(text: str) -> Union[Ingredient, UnparseableIngredient]:
        '''
        >>> Ingredient.parse('asdfag')
        UnparseableIngredient(full='asdfag')
        >>> Ingredient.parse('6 Knoblauchzehen')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='6', unit='', name='Knoblauchzehen',
                   full='6 Knoblauchzehen')
        >>> Ingredient.parse('750 g Wasser')
        Ingredient(amount='750', unit='g', name='Wasser', full='750 g Wasser')
        >>> Ingredient.parse('140 g Urdbohnen, getrocknet (Linsenbohnen)')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='140', unit='g', name='Urdbohnen',
                   full='140 g Urdbohnen, getrocknet (Linsenbohnen)')
        >>> Ingredient.parse('20 g Ingwer, geschält, in Scheiben (2 mm)')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='20', unit='g', name='Ingwer',
                   full='20 g Ingwer, geschält, in Scheiben (2 mm)')
        >>> Ingredient.parse('50 - 70 g Crème double (ca. 48 % Fett)'
        ...                  ' und mehr zum Servieren')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='50 - 70', unit='g', name='Crème double',
                   full='50 - 70 g Crème double (ca. 48 % Fett) und mehr
                         zum Servieren')
        >>> Ingredient.parse('1 Zwiebel, halbiert')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='1', unit='',
                   name='Zwiebel', full='1 Zwiebel, halbiert')
        >>> Ingredient.parse('½ TL Muskat')
        Ingredient(amount='½', unit='TL', name='Muskat', full='½ TL Muskat')
        >>> Ingredient.parse('¼ TL Cayenne-Pfeffer, gemahlen')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='¼', unit='TL', name='Cayenne-Pfeffer',
                   full='¼ TL Cayenne-Pfeffer, gemahlen')
        >>> Ingredient.parse('¾ TL Thymian, getrocknet (optional)')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='¾', unit='TL', name='Thymian',
                   full='¾ TL Thymian, getrocknet (optional)')
        >>> Ingredient.parse('3 ½ TL Salz')
        ... #doctest: +NORMALIZE_WHITESPACE
        Ingredient(amount='3 ½', unit='TL', name='Salz',
                   full='3 ½ TL Salz')
        '''
        match = re.search(r'^\s*(¼|½|¾|\d+(?:\s+(?:\-\s+\d+|½))?)'
                          r'(?:\s+(\S*[^\s,]))?'
                          r'(?:\s+([^,(]*[^,(\s]).*)$',
                          text)
        if match is None:
            return UnparseableIngredient(text)
        return Ingredient(match.group(1),
                          match.group(2) or '',
                          match.group(3) or '',
                          match.group(0))


def recipe_ingredients_checker(args: AppArgs,
                               _: AppConfig,
                               grocy: GrocyApi) -> None:
    ''' assist importing recipes from the web

    Check if ingredients and their units are known to grocy for a recipe to be
    imported
    '''
    response = requests.get(args.url)
    soup = BeautifulSoup(response.text, 'html5lib')
    ingredients = [Ingredient.parse(normanlize_white_space(item.get_text()))
                   for item in soup.select('core-list-section ul li')]
    print(f"Found {len(ingredients)} ingredients")
    products = grocy.get_all_products()
    units = grocy.get_all_quantity_units()
    convertions = grocy.get_all_quantity_unit_convertions()
    product_known = []
    product_unknown = []
    for ingred in ingredients:
        if (isinstance(ingred, UnparseableIngredient)
                or ingred.name not in products
                and ingred.name != ''):
            product_unknown.append(ingred)
        else:
            product_known.append(ingred)
    matching_units = [(ingred, [unit
                                for unit in units
                                if ingred.unit in [unit['name'],
                                                   unit['name_plural']]
                                ])
                      for ingred in product_known]
    unit_convertion_unknown = [ingred
                               for ingred, units in matching_units
                               if any(units)
                               and not any(u['id'] == products[ingred.name
                                                               ]['qu_id_stock']
                                           for u in units)
                               and not any(u['id'] == c['from_qu_id']
                                           and c['to_qu_id']
                                           == products[ingred.name
                                                       ]['qu_id_stock']
                                           and c['product_id'
                                                 ] in [products[ingred.name
                                                                ]['id'],
                                                       None]
                                           for u in units
                                           for c in convertions)]
    # from_qu_id: int
    # to_qu_id: int
    # product_id: Optional[int]

    print('Unknown ingredients:')
    print('\n'.join(str(ingred) for ingred in product_unknown))
    print('\nUnknown units:')
    print('\n'.join(str(ingred)
                    for ingred, units in matching_units
                    if not any(units)))
    print('\nUnknown unit convertion:')
    print('\n'.join(str(ingred)
                    for ingred in unit_convertion_unknown))


def list_rewe_purchases(args: AppArgs, *_: Any) -> None:
    ''' List purchases from REWE

    List purchases from the German supermarket chain REWE
    '''
    print('\n'.join(ReweJsonSchema.load_from_json_file(args.file).list_orders()
                    ))


def get_argparser() -> ArgumentParser:
    ''' ArgumentParser factory method '''
    parser = ArgumentParser(description='Help importing into Grocy')
    parser.add_argument('--dry-run', action='store_true',
                        help='perform a trial run with no changes made')
    subparsers = parser.add_subparsers()
    shoppinglist = subparsers.add_parser('shopping-list',
                                         help='export shopping list in'
                                              ' todo.txt format')
    shoppinglist.set_defaults(func=export_shopping_list)
    recipe = subparsers.add_parser('recipe',
                                   description='Check if ingredients and their'
                                               ' units are known to grocy for'
                                               ' a recipe to be imported',
                                   help='assist importing recipes from the web'
                                   )
    recipe.add_argument('url')
    recipe.set_defaults(func=recipe_ingredients_checker)
    purchase = subparsers.add_parser('purchase', help='import purchases')
    purchase_store = purchase.add_subparsers(metavar='STORE',
                                             required=True,
                                             dest='store')
    netto = purchase_store.add_parser('netto',
                                      help='German discount supermarket chain'
                                           ' Netto Marken-Discount',
                                      description='import a "digitaler'
                                                  ' Kassenbon" email from the'
                                                  ' German discount'
                                                  ' supermarket chain Netto'
                                                  ' Marken-Discount')
    netto.set_defaults(func=import_purchase)
    netto.add_argument('file',
                       type=FileType('r', encoding='utf-8'),
                       help='Path to an e-mail with the "digitaler Kassenbon"')
    rewe = (purchase_store
            .add_parser('rewe',
                        help='German supermarket chain REWE',
                        description='Import from DSGVO provided'
                                    ' "Meine REWE-Shop-Daten.json"')
            .add_subparsers(metavar='ACTION', required=True))
    rewe_list = rewe.add_parser('list', help='list the purchases')
    rewe_list.set_defaults(func=list_rewe_purchases)
    rewe_import = rewe.add_parser('import',
                                  help='import a purchase')
    rewe_import.set_defaults(func=import_purchase)
    rewe_import.add_argument('--order', type=int, default=1, metavar='N',
                             help='Which order to import. Defaults to 1'
                                  ' (the latest)')
    for subcommand in [rewe_import, rewe_list]:
        subcommand.add_argument('file',
                                type=FileType('r', encoding='utf-8'),
                                help='Path to "Meine REWE-Shop-Daten.json"'
                                     ' file. Downloadable from'
                                     ' https://shop.rewe.de/mydata/privacy'
                                     ' under "Meine Daten anfordern"')
    return parser


def find_shopping_location_for(store: str,
                               options: Iterable[GrocyShoppingLocation]
                               ) -> GrocyShoppingLocation:
    ''' Find the grocy shopping location for given `store`'''
    try:
        return sorted(filter(lambda o: o['name'].lower().startswith(store),
                             options),
                      key=lambda o: o['name'].lower())[0]
    except IndexError as ex:
        raise UserError(f"No shopping location found for '{store}'.") from ex


def get_shopping_location_id(store: Literal['netto', 'rewe'],
                             config: AppConfig,
                             grocy: GrocyApi
                             ) -> int:
    ''' grocy's shopping location id '''
    try:
        return int(config[store]['shopping_location_id'])
    except KeyError:
        return find_shopping_location_for(store,
                                          grocy.get_all_shopping_locations()
                                          )['id']


def convert_unit(convertions: Iterable[GrocyQUnitConvertion],
                 from_qu_id: int,
                 to_qu_id: int,
                 product_id: Optional[int]
                 ) -> float:
    '''
    The factor for a unit convertion for a given product.

    >>> convert_unit([], 42, 42, None)
    1
    >>> convert_unit([{'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': None, 'factor': 1.5}
    ...              ], 7, 42, None)
    1.5
    >>> convert_unit([{'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': 121, 'factor': 3.5}
    ...              ], 7, 42, 121)
    3.5
    >>> convert_unit([{'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': 121, 'factor': 3.5},
    ...               {'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': None, 'factor': 1.5},
    ...              ], 7, 42, 121)
    3.5
    >>> convert_unit([{'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': 121, 'factor': 3.5},
    ...               {'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': None, 'factor': 1.5},
    ...              ], 7, 42, None)
    1.5
    >>> convert_unit([{'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': 121, 'factor': 3.5},
    ...               {'id': 1, 'from_qu_id': 7, 'to_qu_id': 42,
    ...                'product_id': None, 'factor': 1.5},
    ...              ], 7, 42, 144)
    1.5
    '''
    if from_qu_id == to_qu_id:
        return 1
    return sorted([c
                   for c in convertions
                   if c['from_qu_id'] == from_qu_id
                   and c['to_qu_id'] == to_qu_id
                   and c['product_id'] in [None, product_id]],
                  key=lambda o: o['product_id'] is None
                  )[0]['factor']


def import_purchase(args: AppArgs,
                    config: AppConfig,
                    grocy: GrocyApi) -> None:
    ''' help importing multiple purchases into grocy '''
    stores = {'netto': netto_purchase,
              'rewe': rewe_purchase}
    groceries = stores[args.store](args)
    barcodes = grocy.get_all_product_barcodes()
    products = grocy.get_all_products_by_id()
    shopping_location = get_shopping_location_id(args.store, config, grocy)
    factor = partial(convert_unit, grocy.get_all_quantity_unit_convertions())
    while any(unknown_items := [str(item)
                                for item in groceries
                                if item.name not in barcodes]):
        print('Unknown products. Please add to grocy:')
        print('\n'.join(unknown_items))
        input('...')
        barcodes = grocy.get_all_product_barcodes()
    for item in groceries:
        pro = barcodes[item.name]
        grocy.purchase(pro['product_id'],
                       item.amount
                       * pro['amount']
                       * factor(pro['qu_id'],
                                products[pro['product_id']]['qu_id_stock'],
                                pro['product_id']),
                       item.price,
                       shopping_location
                       )
        print(f'Added {item}')


def format_shopping_list_item(item: GrocyShoppingListItem,
                              known_products: dict[int, GrocyProduct],
                              units: dict[int, GrocyQuantityUnit],
                              _: dict[int, GrocyProductGroup]
                              ) -> str:
    ''' Format shopping list item in todo.txt format '''
    product = known_products[item["product_id"]]
    name = product["name"]
    unit = units[item["qu_id"]]["name_plural"]
    return f'{name}, {item["amount"]}{unit}'


def export_shopping_list(_: AppArgs,
                         __: AppConfig,
                         grocy: GrocyApi) -> None:
    ''' export shopping list to todo.txt '''
    known_products = grocy.get_all_products_by_id()
    shopping_list = grocy.get_all_shopping_list()
    units = grocy.get_all_quantity_units_by_id()
    groups = grocy.get_all_product_groups()

    def product_group_id(item: GrocyShoppingListItem) -> int:
        return known_products[item['product_id']]['product_group_id'] or 0

    print('\n'.join(format_shopping_list_item(item,
                                              known_products,
                                              units,
                                              groups)
                    for item in sorted(shopping_list, key=product_group_id)))


def main() -> None:
    ''' Run the CLI program '''
    args = cast(AppArgs, get_argparser().parse_args())
    config_path = join(user_config_dir('grocy-importer', 'adaschma.name'),
                       'config.ini')
    config_parser = ConfigParser()
    config_parser.read(config_path)
    config = cast(AppConfig, config_parser)
    try:
        grocy = GrocyApi(**config['grocy'], dry_run=args.dry_run)
    except KeyError as ex:
        raise UserError(f"Configfile '{config_path}'"
                        " is missing or incomplete."
                        ) from ex
    else:
        args.func(args, config, grocy)


if __name__ == '__main__':
    try:
        main()
    except UserError as err:
        sys.exit(f"Error: {err}")
