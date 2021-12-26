#!/usr/bin/python3

''' Help importing into Grocy '''

from argparse import ArgumentParser, FileType
import re
from email.parser import Parser
from typing import Union, Iterable, Optional, TextIO
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import join
import sys
import json

from bs4 import BeautifulSoup
import requests
from marshmallow import Schema, fields, EXCLUDE, post_load
from appdirs import user_config_dir


class GrocyApi:
    ''' Calls to the Grocy REST-API '''

    def __init__(self, api_key: str, base_url: str, dry_run: bool):
        self.headers = {'GROCY-API-KEY': api_key}
        self.base_url = base_url
        self.dry_run = dry_run

    def get_all_products(self):
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers)
        return {p['name']: p for p in response.json()}

    def purchase(self, product_id: int, amount: float, price: str,
                 shopping_location_id: int):
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


def cleanup_product_name(orig: str) -> str:
    ''' Remove multiple white space '''
    return re.sub(r'\s+', ' ', orig)


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
                     cleanup_product_name(args[0]))
            if len(args) == 2
            else Purchase(float(args[0].split()[0]),
                          from_netto_price(args[2]),
                          cleanup_product_name(args[1])))


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


def rewe_purchase(args) -> list[Purchase]:
    ''' Import from REWE '''
    data = ReweJsonSchema.load_from_json_file(args.file)
    return [Purchase(line_item.quantity,
                     line_item.total_price,
                     line_item.title)
            for line_item in data.sorted_orders()[args.order-1
                                                  ].sub_orders[0].line_items
            if line_item.title not in ['TimeSlot',
                                       'Enthaltene Pfandbeträge',
                                       'Getränke-Sperrgutaufschlag']]


def netto_purchase(args) -> list[Purchase]:
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
    def make(self, data, **_) -> ReweJsonLineItem:
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
    def make(self, data, **_) -> ReweJsonSuborder:
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
    def make(self, data, **_) -> ReweJsonOrder:
        ''' Create instance from deserialized data '''
        return ReweJsonOrder(**data)


class ReweJsonOrdersListSchema(Schema):
    ''' Represents data from "Meine REWE-Shop-Daten.json" '''
    orders = fields.List(fields.Nested(ReweJsonOrderSchema, unknown=EXCLUDE))

    @post_load
    def make(self, data, **_) -> ReweJsonOrdersList:
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
        return ReweJsonSchema(unknown=EXCLUDE).load(json.load(file),
                                                    unknown=EXCLUDE)

    @post_load
    def make(self, data, **__) -> ReweJson:
        ''' Create instance from deserialized data '''
        return ReweJson(**data)


def list_rewe_purchases(args, *_) -> None:
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


def import_purchase(args,
                    config: ConfigParser,
                    grocy: GrocyApi):
    ''' help importing multiple purchases into grocy '''
    stores = {'netto': netto_purchase,
              'rewe': rewe_purchase}
    groceries = stores[args.store](args)
    known_products = grocy.get_all_products()
    shopping_location = int(config[args.store]['shopping_location_id'])
    while any(unknown_items := [str(item)
                                for item in groceries
                                if item.name not in known_products]):
        print('Unknown products. Please add to grocy:')
        print('\n'.join(unknown_items))
        input('...')
        known_products = grocy.get_all_products()
    for item in groceries:
        pro = known_products[item.name]
        grocy.purchase(pro['id'],
                       item.amount * float(pro['qu_factor_purchase_to_stock']),
                       item.price,
                       shopping_location
                       )
        print(f'Added {item}')


def main():
    ''' Run the CLI program '''
    args = get_argparser().parse_args()
    config_path = join(user_config_dir('grocy-importer', 'adaschma.name'),
                       'config.ini')
    config = ConfigParser()
    config.read(config_path)
    try:
        grocy = GrocyApi(**config['grocy'], dry_run=args.dry_run)
    except KeyError:
        sys.exit(f"Error: Configfile '{config_path}' is missing or incomplete."
                 )
    else:
        args.func(args, config, grocy)


if __name__ == '__main__':
    main()
