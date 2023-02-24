#!/usr/bin/python3

''' Help importing into Grocy '''

from __future__ import annotations

from argparse import ArgumentParser, FileType
import re
from abc import (ABC, abstractmethod)
from email.parser import Parser
from typing import (Union, Iterable, Mapping, Optional, TextIO, TypedDict,
                    Literal, Callable, cast, Any, NotRequired)
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import join
import sys
import json
from functools import partial
from logging import getLogger
from datetime import datetime, timedelta
from os import environ
import webbrowser

from bs4 import BeautifulSoup
import requests
from marshmallow import Schema, fields, EXCLUDE, post_load
from appdirs import user_config_dir
import argcomplete


logger = getLogger(__name__)


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
    location_id: int


class GrocyLocation(TypedDict):
    ''' A location as returned from the Grocy API '''
    id: int
    name: str


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


class GrocyChoreDetailCore(TypedDict):
    ''' The main part of the chore of a chore detail from the Grocy API '''
    id: int
    name: str


class GrocyChoreDetail(TypedDict):
    ''' A chore detail as returned from the Grocy API '''
    chore: GrocyChoreDetailCore


def chore_from_detail(orig: GrocyChoreDetail) -> GrocyChore:
    ''' Convert to a GrocyChore '''
    return {'id': orig["chore"]["id"], 'chore_name': orig["chore"]["name"]}


class GrocyChore(TypedDict):
    ''' A chore as returned from the Grocy API via /chore '''
    id: int
    chore_name: str
    rescheduled_date: NotRequired[Optional[str]]


class GrocyChoreFull(TypedDict):
    ''' A chore as returned from Grocy API via /object '''
    id: int
    name: str
    rescheduled_date: NotRequired[Optional[str]]


class GrocyApi:
    ''' Calls to the Grocy REST-API '''

    def __init__(self, api_key: str, base_url: str, dry_run: bool, timeout: int
                 ):
        self.headers = {'GROCY-API-KEY': api_key,
                        'Content-type': 'application/json'}
        self.base_url = base_url
        self.dry_run = dry_run
        self.only_active = {'query[]': ['active=1']}
        self.timeout = timeout

    def get_all_product_barcodes(self) -> dict[str, GrocyProductBarCode]:
        ''' all product barcodes known to grocy '''
        response = requests.get(self.base_url + '/objects/product_barcodes',
                                headers=self.headers,
                                timeout=self.timeout)
        return {p['barcode']: p for p in response.json()}

    def get_all_products(self) -> dict[str, GrocyProduct]:
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers,
                                params=self.only_active,
                                timeout=self.timeout)
        return {p['name']: p for p in response.json()}

    def rearrange_by_id(self, by_name: dict[str, GrocyProduct]
                        ) -> dict[int, GrocyProduct]:
        ''' convinience to rearrange given known products by id '''
        return {p['id']: p for p in by_name.values()}

    def get_all_products_by_id(self) -> dict[int, GrocyProduct]:
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers,
                                params=self.only_active,
                                timeout=self.timeout)
        return {p['id']: p for p in response.json()}

    def get_all_product_groups(self) -> dict[int, GrocyProductGroup]:
        ''' all product groups known to grocy '''
        response = requests.get(self.base_url + '/objects/product_groups',
                                headers=self.headers,
                                timeout=self.timeout)
        return {p['id']: p for p in response.json()}

    def get_all_shopping_locations(self) -> Iterable[GrocyShoppingLocation]:
        ''' all shopping locations known to grocy '''
        response = requests.get(self.base_url + '/objects/shopping_locations',
                                headers=self.headers,
                                timeout=self.timeout)
        return cast(Iterable[GrocyShoppingLocation], response.json())

    def get_location_names(self) -> Mapping[int, str]:
        ''' all (storage) locations known to grocy '''
        response = requests.get(self.base_url + '/objects/locations',
                                headers=self.headers,
                                timeout=self.timeout)
        return {location['id']: location['name']
                for location in cast(Iterable[GrocyLocation], response.json())}

    def get_all_quantity_units(self) -> Iterable[GrocyQuantityUnit]:
        ''' all quantity units known to grocy '''
        response = requests.get(self.base_url + '/objects/quantity_units',
                                headers=self.headers,
                                timeout=self.timeout)
        return cast(Iterable[GrocyQuantityUnit], response.json())

    def get_all_quantity_units_by_id(self) -> dict[int, GrocyQuantityUnit]:
        ''' all quantity units known to grocy '''
        response = requests.get(self.base_url + '/objects/quantity_units',
                                headers=self.headers,
                                timeout=self.timeout)
        return {p['id']: p for p in response.json()}

    def get_all_quantity_unit_convertions(self
                                          ) -> Iterable[GrocyQUnitConvertion]:
        ''' all quantity unit convertions known to grocy '''
        response = requests.get(self.base_url
                                + '/objects/quantity_unit_conversions',
                                headers=self.headers,
                                timeout=self.timeout)
        return cast(Iterable[GrocyQUnitConvertion], response.json())

    def get_all_shopping_list(self) -> Iterable[GrocyShoppingListItem]:
        ''' all items on shopping lists '''
        response = requests.get(self.base_url
                                + '/objects/shopping_list',
                                headers=self.headers,
                                timeout=self.timeout)
        return cast(Iterable[GrocyShoppingListItem], response.json())

    def get_overdue_chores(self, now: datetime) -> Iterable[GrocyChore]:
        ''' all chores that are overdue '''
        response = requests.get(self.base_url
                                + '/chores',
                                headers=self.headers,
                                params={'query[]':
                                        ['next_estimated_execution_time<'
                                         + now.strftime('%F %T')]},
                                timeout=self.timeout)
        return cast(Iterable[GrocyChore], response.json())

    def get_scheduled_manual_chores(self, now: datetime
                                    ) -> Iterable[GrocyChoreFull]:
        ''' all manual chores that are scheduled '''
        response = requests.get(f'{self.base_url}/objects/chores',
                                headers=self.headers,
                                params={'query[]':
                                        ['period_type=manually',
                                         'active=1',
                                         'rescheduled_date>'
                                         + now.strftime('%F %T')
                                         ]},
                                timeout=self.timeout)
        return cast(Iterable[GrocyChoreFull], response.json())

    def schedule_chore(self, chore_id: int, date_time: str
                       ) -> None:
        if self.dry_run:
            return
        data = {'rescheduled_date': date_time}
        response = requests.put(f'{self.base_url}/objects/chores/{chore_id}',
                                headers=self.headers,
                                json=data,
                                timeout=self.timeout)
        assert response.status_code//100 == 2, response.reason

    def did_chore(self, chore_id: int, tracked_time: Optional[str],
                  skip: bool = False,
                  ) -> GrocyChore:
        ''' Mark a chore as done '''
        if self.dry_run:
            return self.get_chore(chore_id)
        data = ({}
                if tracked_time is None
                else {'tracked_time': tracked_time,
                      'done_by': 0, 'skipped': skip})
        logger.debug(data)
        response = requests.post(f'{self.base_url}/chores/{chore_id}/execute',
                                 headers=self.headers,
                                 json=data,
                                 timeout=self.timeout)
        assert response.status_code//100 == 2, response.reason
        return cast(GrocyChore, response.json())

    def get_chore(self, chore_id: int) -> GrocyChore:
        ''' Get a chore from grocy '''
        url = f'{self.base_url}/chores/{chore_id}'
        response = requests.get(url,
                                headers=self.headers,
                                timeout=self.timeout)
        assert response.status_code//100 == 2, f'{url} {response.reason}'
        return chore_from_detail(cast(GrocyChoreDetail, response.json()))

    def purchase(self, product_id: int, amount: float, price: float,
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
                                       },
                                 timeout=self.timeout)
        assert response.status_code//100 == 2, response.reason


@dataclass
class AppArgs:
    ''' Common args '''
    dry_run: bool
    timeout: int
    chores: list[int]
    func: Callable[[AppArgs, AppConfig, GrocyApi], None]


@dataclass
class CliArgs(AppArgs):
    ''' Structure of our CLI args '''
    regex: str
    store: Literal['netto', 'rewe']
    file: TextIO
    order: int
    url: str
    show: bool
    skip: bool
    days: int
    at: Optional[str]
    keep: Literal['later', 'earlier', 'old', 'new']


@dataclass
class TodotxtArgs(AppArgs):
    ''' Structure of our todo-txt CLI args '''
    environ: TodotxtEnvVariables


def normanlize_white_space(orig: str) -> str:
    ''' Remove multiple white space '''
    return re.sub(r'\s+', ' ', orig).strip()


@dataclass
class Purchase:
    ''' Represents an item purchased.

    Unlike Grocy the price is that total rather then per unit.
    '''
    amount: Union[int, float]
    price: float
    name: str


def simplify(items: Iterable[Purchase]
             ) -> list[Purchase]:
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


class Store(ABC):
    ''' Base class for store backends. '''

    @property
    @abstractmethod
    def store_info(self) -> StoreSubcommandInfo:
        ''' The information to use in the subcommand for the store.
        '''

    @abstractmethod
    def get_purchase(self, args: CliArgs) -> list[Purchase]:
        ''' Returns a list of the Items for a given purchase
        '''

    def list_purchases(self, _args: CliArgs, *_: Any) -> None:
        ''' List purchases from store

        List purchases from the store. Override this method if the store file
        contains multiple purchases and not just one. In that case also
        set `store_info.includes_history = True`.
        '''

    def create_subcommand(self,
                          purchase_store: Any
                          ) -> None:
        'store subcommands'
        store = (purchase_store
                 .add_parser(self.store_info.name,
                             help=self.__doc__,
                             description=self.store_info.help_description)
                 .add_subparsers(metavar='ACTION', required=True))
        active_subcommands = self.get_subcommands(store)
        for subcommand in active_subcommands:
            subcommand.add_argument('file',
                                    type=FileType('r', encoding='utf-8'),
                                    help=self.store_info.file_help_msg)

    def get_subcommands(self, store: Any) -> Iterable[Any]:
        import_cmd = store.add_parser('import',
                                      help='import a purchase')
        import_cmd.set_defaults(func=self.import_purchase)
        active_subcommands = [import_cmd]
        if self.store_info.includes_history:
            list_cmd = store.add_parser('list', help='list the purchases')
            list_cmd.set_defaults(func=self.list_purchases)
            import_cmd.add_argument('--order', type=int, default=1,
                                    metavar='N',
                                    help='Which order to import. Defaults to'
                                         ' 1 (the latest)')
            active_subcommands.append(list_cmd)
        return active_subcommands

    def import_purchase(self,
                        args: CliArgs,
                        config: AppConfig,
                        grocy: GrocyApi) -> None:
        ''' help importing purchases into grocy '''
        groceries = self.get_purchase(args)
        barcodes = grocy.get_all_product_barcodes()
        shopping_location = get_shopping_location_id(args.store, config, grocy)
        factor = partial(convert_unit,
                         grocy.get_all_quantity_unit_convertions())
        while any(unknown_items := [str(item)
                                    for item in groceries
                                    if item.name not in barcodes]):
            print('Unknown products. Please add to grocy:', file=sys.stderr)
            print('\n'.join(unknown_items), file=sys.stderr)
            input('...')
            barcodes = grocy.get_all_product_barcodes()
        products = grocy.get_all_products_by_id()
        grocy_purchases = []
        for item in groceries:
            try:
                pro = barcodes[item.name]
                grocy_purchases.append(partial(grocy.purchase,
                                               pro['product_id'],
                                               item.amount
                                               * pro['amount']
                                               * factor(pro['qu_id'],
                                                        products[pro
                                                                 ['product_id'
                                                                  ]
                                                                 ]
                                                        ['qu_id_stock'],
                                                        pro['product_id']),
                                               item.price / item.amount,
                                               shopping_location
                                               ))
            except Exception:
                print(f'Failed {item}')
                raise
            logger.debug('Prepared %s', item)
        for func, item in zip(grocy_purchases, groceries):
            func()
            print(f'Added {item}')


@dataclass
class StoreSubcommandInfo:
    ''' Information needed in the subcommand. '''
    name: str
    help_description: str
    file_help_msg: str
    includes_history: bool = False


class Rewe(Store):
    'German supermarket chain REWE'

    @property
    def store_info(self) -> StoreSubcommandInfo:
        return StoreSubcommandInfo(
            'rewe',
            'Import from DSGVO provided "Meine REWE-Shop-Daten.json"',
            '''
            Path to "Meine REWE-Shop-Daten.json" file. Downloadable from
            https://shop.rewe.de/mydata/privacy under "Meine Daten anfordern"
            ''',
            includes_history=True)

    def list_purchases(self, _args: CliArgs, *_: Any) -> None:
        print('\n'.join(ReweJsonSchema.load_from_json_file(_args.file
                                                           ).list_orders()
                        ))

    def get_purchase(self, args: CliArgs) -> list[Purchase]:
        data = ReweJsonSchema.load_from_json_file(args.file)
        return [Purchase(line_item.quantity,
                         line_item.total_price / 100,
                         line_item.title)
                for line_item in data.sorted_orders()[args.order-1
                                                      ].sub_orders[0
                                                                   ].line_items
                if line_item.title not in ['TimeSlot',
                                           'Enthaltene Pfandbeträge',
                                           'Getränke-Sperrgutaufschlag']]

    def get_subcommands(self, store: Any) -> Iterable[Any]:
        yield from super().get_subcommands(store)
        order = store.add_parser('order',
                                 help='order items from shopping list')
        order.set_defaults(func=self.place_order)

    def place_order(self,
                    args: CliArgs,
                    config: AppConfig,
                    grocy: GrocyApi) -> None:
        items = grocy.get_all_shopping_list()
        products = grocy.get_all_products_by_id()
        units = grocy.get_all_quantity_units_by_id()
        for p in items:
            webbrowser.open("https://shop.rewe.de/productList?"
                            f"search={products[p['product_id']]['name']}"
                            f"&quantity={p['amount']}"
                            f" {units[p['qu_id']]['name_plural']}")


class Netto(Store):
    'German discount supermarket chain Netto Marken-Discount'

    @property
    def store_info(self) -> StoreSubcommandInfo:
        return StoreSubcommandInfo(
            'netto',
            '''
            Import a "digitaler Kassenbon" email from the German discount
            supermarket chain Netto Marken-Discount
            ''',
            'Path to an e-mail with the "digitaler Kassenbon"',
            )

    def get_purchase(self, args: CliArgs) -> list[Purchase]:
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
                        in soup.select(' '.join(7*["tbody"] + ["tr"]))
                        if not list(row.select('td')
                                    )[0].get_text().endswith(':')
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
        return simplify(self._parse_purchase(item)
                        for item in items if len(item) > 1)

    def _parse_purchase(self, args: list[str]) -> Purchase:
        ''' Parse a Netto store purchase '''
        return (Purchase(1,
                         self._from_netto_price(args[1]),
                         normanlize_white_space(args[0]))
                if len(args) == 2
                else Purchase(float(args[0].split()[0]),
                              self._from_netto_price(args[2]),
                              normanlize_white_space(args[1])))

    def _from_netto_price(self, netto_price: str) -> float:
        ''' convert from Netto store price format to grocy's '''
        return float(netto_price.split()[0].replace(',', '.'))


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
            yield (f'{i+1}. {date[:4]}-{date[4:6]}-{date[6:8]} {merchant}'
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


def cookidoo_ingredients(url: str, timeout: int
                         ) -> list[Union[Ingredient, UnparseableIngredient]]:
    ''' Find all ingrediant of the recipe '''
    response = requests.get(url, timeout=timeout)
    soup = BeautifulSoup(response.text, 'html5lib')
    ingredients = [Ingredient.parse(normanlize_white_space(item.get_text())
                                    )
                   for item in soup.select('core-list-section ul li')]
    return ingredients


@dataclass
class NormalizedIngredientsResult:
    ''' Categorized Ingredients  '''
    product_unknown: list[UnparseableIngredient | Ingredient]
    matching_units: list[tuple[Ingredient, list[GrocyQuantityUnit]]]
    unit_convertion_unknown: list[Ingredient]

    def print(self) -> None:
        ''' Output a human readable summary '''
        print('Unknown ingredients:')
        print('\n'.join(str(ingred) for ingred in self.product_unknown))
        print('\nUnknown units:')
        print('\n'.join(str(ingred)
                        for ingred, units in self.matching_units
                        if not any(units)))
        print('\nUnknown unit convertion:')
        print('\n'.join(str(ingred)
                        for ingred in self.unit_convertion_unknown))


@dataclass
class IngredientNormalizer:
    ''' WIP
    '''
    barcodes: dict[str, GrocyProductBarCode]
    products: dict[str, GrocyProduct]
    products_by_id: dict[int, GrocyProduct]
    units: Iterable[GrocyQuantityUnit]
    convertions: Iterable[GrocyQUnitConvertion]

    def apply_alias(self, ingredient: Ingredient,
                    ) -> Ingredient:
        ''' Return an Ingredient with cononical name '''
        alias = self.barcodes[ingredient.name]
        unit = (ingredient.unit
                if ingredient.unit != ''
                else {u['id']: u['name'] for u in self.units}[alias['qu_id']])
        return Ingredient(ingredient.amount,
                          unit,
                          self.products_by_id[alias['product_id']]['name'],
                          ingredient.full)

    def match_with_grocy(self,
                         ingredients: list[Union[Ingredient,
                                                 UnparseableIngredient]]
                         ) -> NormalizedIngredientsResult:
        ''' WIP '''
        product_known = []
        product_unknown: list[Union[Ingredient, UnparseableIngredient]] = []
        for ingred in ingredients:
            if isinstance(ingred, UnparseableIngredient):
                product_unknown.append(ingred)
            elif ingred.name not in self.products and ingred.name != '':
                try:
                    product_known.append(self.apply_alias(ingred))
                except KeyError:
                    product_unknown.append(ingred)
            else:
                product_known.append(ingred)
        matching_units = [(ingred, [unit
                                    for unit in self.units
                                    if ingred.unit in [unit['name'],
                                                       unit['name_plural']]
                                    ])
                          for ingred in product_known]
        convertion_unknown = [ingred
                              for ingred, units in matching_units
                              if any(units)
                              and not any(self.products[ingred.name
                                                        ]['qu_id_stock']
                                          == u['id']
                                          for u in units)
                              and not any(u['id'] == c['from_qu_id']
                                          and c['to_qu_id']
                                          == self.products[ingred.name
                                                           ]['qu_id_stock']
                                          and c['product_id'
                                                ] in [self.products[ingred.name
                                                                    ]['id'],
                                                      None]
                                          for u in units
                                          for c in self.convertions)]
        return NormalizedIngredientsResult(product_unknown,
                                           matching_units,
                                           convertion_unknown)


def recipe_ingredients_checker(args: CliArgs,
                               _: AppConfig,
                               grocy: GrocyApi) -> None:
    ''' assist importing recipes from the web

    Check if ingredients and their units are known to grocy for a recipe to be
    imported
    '''
    ingredients = cookidoo_ingredients(args.url, args.timeout)
    logger.info("Found %s ingredients", len(ingredients))
    products = grocy.get_all_products()
    products_by_id = grocy.rearrange_by_id(products)
    units = grocy.get_all_quantity_units()
    convertions = grocy.get_all_quantity_unit_convertions()
    barcodes = grocy.get_all_product_barcodes()
    normalizer = IngredientNormalizer(barcodes,
                                      products,
                                      products_by_id,
                                      units,
                                      convertions)
    normalizer.match_with_grocy(ingredients).print()
    # from_qu_id: int
    # to_qu_id: int
    # product_id: Optional[int]


def human_agrees(question: str) -> bool:
    ''' Ask human a yes/no question '''
    answer = input(question + ' [y/n]')
    return 'y' in answer


def chore_did_cmd(args: CliArgs,
                  _: AppConfig,
                  grocy: GrocyApi) -> None:
    ''' Mark chore(s) as done.
    '''
    if len(args.chores) > 0:
        for chore_id in args.chores:
            grocy.did_chore(chore_id, args.at, args.skip)
        return
    now = datetime.now()
    for chore in grocy.get_overdue_chores(now):
        if human_agrees(f'Completed {chore["chore_name"]}?'):
            grocy.did_chore(chore['id'], args.at, args.skip)
    for choreFull in grocy.get_scheduled_manual_chores(now):
        if human_agrees(f'Completed {choreFull["name"]}?'):
            grocy.did_chore(chore['id'], args.at, args.skip)


def chore_schedule_cmd(args: CliArgs,
                       _: AppConfig,
                       grocy: GrocyApi) -> None:
    ''' Schedule chore(s).
    '''
    at = args.at or (datetime.now() + timedelta(days=args.days)
                     ).strftime('%Y-%m-%d %H:%M:%S')
    for chore_id in args.chores:
        try:
            prev_schedule = grocy.get_chore(chore_id)['rescheduled_date']
        except KeyError:
            pass
        else:
            if prev_schedule is not None and (args.keep == 'old'
                                              or prev_schedule < at and
                                              args.keep == 'earlier'
                                              or prev_schedule > at and
                                              args.keep == 'later'
                                              ):
                at = prev_schedule
        grocy.schedule_chore(chore_id, at)


def chore_show_cmd(args: AppArgs,
                   _: AppConfig,
                   grocy: GrocyApi) -> None:
    ''' Show chore(s).
    '''
    if len(args.chores) > 0:
        for chore_id in args.chores:
            chore = grocy.get_chore(chore_id)
            print(chore["chore_name"])
        return
    now = datetime.now()
    for chore in grocy.get_overdue_chores(now):
        print(f'{chore["id"]}: {chore["chore_name"]}')
    for choreFull in grocy.get_scheduled_manual_chores(now):
        print(f'{chore["id"]}: {choreFull["name"]}'
              f' ({choreFull["rescheduled_date"]})')


def find_item(args: CliArgs,
              _: AppConfig,
              grocy: GrocyApi) -> None:
    ''' Find default location of a product '''
    locations = grocy.get_location_names()
    products = [p
                for (name, p) in grocy.get_all_products().items()
                if re.search(args.regex, name, re.I)]
    print('\n'.join(f'{p["name"]}: {locations[p["location_id"]]}'
                    for p in products))


def common_argument_parser(description: str) -> ArgumentParser:
    parser = ArgumentParser(description=description)
    parser.add_argument('--timeout', metavar='N', default=10, type=int,
                        help='Override the default timeout for each REST call')
    parser.add_argument('--dry-run', action='store_true',
                        help='perform a trial run with no changes made')
    return parser


@dataclass
class TodotxtEnvVariables(object):
    TODO_FULL_SH: str
    TODO_FILE: str


def get_todotxt_parser(environ: TodotxtEnvVariables) -> ArgumentParser:
    ''' ArgumentParser factory method for todo.txt plugin '''
    parser = common_argument_parser(description='Interact with Grocy chores')
    parser.set_defaults(environ=environ)
    toplevel = parser.add_subparsers()
    chore = toplevel.add_parser('chore')
    chore.set_defaults(func=lambda _, __, ___: chore.print_help())
    subparsers = chore.add_subparsers()
    chore_show = subparsers.add_parser('ls')
    chore_show.set_defaults(func=chore_show_cmd)
    chore_show.add_argument('chores', type=int, nargs='*')

    chore_add = subparsers.add_parser('add')
    # chore_add.set_defaults(func=todotxt_chore_add)
    chore_add.add_argument('chores', type=int, nargs='+')

    usage = toplevel.add_parser('usage')
    usage.set_defaults(func=lambda _, __, ___: chore.print_help())
    return parser


def get_argparser_cli(stores: Iterable[Store]) -> ArgumentParser:
    ''' ArgumentParser factory method '''
    parser = common_argument_parser(description='Help importing into Grocy')
    subparsers = parser.add_subparsers()
    whereis = subparsers.add_parser('whereis',
                                    help='show location of a product')
    whereis.add_argument('regex')
    whereis.set_defaults(func=find_item)
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
    for store in stores:
        store.create_subcommand(purchase_store)
    chore = subparsers.add_parser('chore',
                                  help='Prompt to do each overdue chore'
                                  ).add_subparsers()
    chore_did = chore.add_parser('did',
                                 help='Mark chore as done')
    chore_did.set_defaults(func=chore_did_cmd)
    chore_did.add_argument('chores', type=int, nargs='*')
    chore_did.add_argument('--skip', action='store_true')
    chore_did.add_argument('--at',
                           metavar='y-m-d h:m:s',
                           help="Time the chore was done in Grocy's time"
                                " format. E.g. '2022-11-01 08:41:00',")
    chore_schedule = chore.add_parser('schedule',
                                      help='Schedule a chore')
    chore_schedule.set_defaults(func=chore_schedule_cmd)
    chore_schedule.add_argument('chores', type=int, nargs='+')
    chore_schedule.add_argument('--at',
                                metavar='y-m-d h:m:s',
                                help="The scheduled time in Grocy's time"
                                     " format. E.g. '2022-11-01 08:41:00',")
    chore_schedule.add_argument('--keep',
                                choices=['later', 'earlier', 'old', 'new'],
                                default='new')
    chore_schedule.add_argument('--days', type=int, default=0)
    chore_show = chore.add_parser('show',
                                  help='Show given chore')
    chore_show.set_defaults(func=chore_show_cmd)
    chore_show.add_argument('chores', type=int, nargs='*')
    return parser


def get_argparser(stores: Iterable[Store]) -> ArgumentParser:
    try:
        return get_todotxt_parser(TodotxtEnvVariables(environ['TODO_FULL_SH'],
                                                      environ['TODO_FILE']))
    except KeyError:
        return get_argparser_cli(stores)


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
    try:
        return sorted([c
                       for c in convertions
                       if c['from_qu_id'] == from_qu_id
                       and c['to_qu_id'] == to_qu_id
                       and c['product_id'] in [None, product_id]],
                      key=lambda o: o['product_id'] is None
                      )[0]['factor']
    except IndexError:
        sys.exit(f'No convertion found for {from_qu_id} to {to_qu_id} for'
                 f' {product_id}')


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


def export_shopping_list(_: CliArgs,
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
    argparser = get_argparser([Netto(), Rewe()])
    argcomplete.autocomplete(argparser)
    args = cast(AppArgs, argparser.parse_args())
    config_path = join(user_config_dir('grocy-importer', 'adaschma.name'),
                       'config.ini')
    config_parser = ConfigParser()
    config_parser.read(config_path)
    config = cast(AppConfig, config_parser)
    try:
        grocy = GrocyApi(**config['grocy'], dry_run=args.dry_run,
                         timeout=args.timeout)
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
