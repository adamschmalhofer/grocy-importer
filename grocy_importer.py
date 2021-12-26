#!/usr/bin/python3

''' Help importing into Grocy '''

from argparse import ArgumentParser, FileType
import re
from sys import argv
from email.parser import Parser
from typing import Union, Iterable, Optional
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import dirname, abspath, join
import json

from bs4 import BeautifulSoup
import requests
from marshmallow import Schema, fields, EXCLUDE, post_load


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
        assert response.status_code/100 == 2


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
    price: int
    quantity: int
    title: str
    totalPrice: int


@dataclass
class ReweJsonSuborder:
    deliveryType: str
    # coupons: fields.List()
    # merchantInfo: object
    orderType: str
    paybackNumber: Optional[str]
    channel: str
    # deliveryAddress: object
    subOrderValue: int
    lineItems: list[ReweJsonLineItem]
    # timeSlot: object
    additionalEmail: str
    userComment: str
    merchant: str


@dataclass
class ReweJsonOrder:
    # payments: fields.List()
    # invoiceAddress: object
    orderValue: int
    clientInfo: str
    # paymentInfo: object
    subOrders: list[ReweJsonSuborder]
    # OrderId: str
    creationDate: str


@dataclass
class ReweJsonOrdersList:
    orders: list[ReweJsonOrder]


@dataclass
class ReweJson:
    # addressData: fields.List()
    # deliveryflats: fields.List()
    # payback: object
    # customerData: object
    # paymentData: object
    orders: ReweJsonOrdersList
    # coupons: object


class ReweJsonLineItemSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    price = fields.Integer()
    quantity = fields.Integer()
    title = fields.Str()
    totalPrice = fields.Integer()

    @post_load
    def make(self, data, **kwargs) -> ReweJsonLineItem:
        return ReweJsonLineItem(**data)


class ReweJsonSuborderSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    deliveryType = fields.Str()
    # coupons = fields.List()
    # merchantInfo: object
    orderType = fields.Str()
    paybackNumber = fields.Str(allow_none=True)
    channel = fields.Str()
    # deliveryAddress: object
    subOrderValue = fields.Integer()
    lineItems = fields.List(fields.Nested(ReweJsonLineItemSchema,
                                          unkown=EXCLUDE))
    # timeSlot: object
    additionalEmail = fields.Str()
    userComment = fields.Str()
    merchant = fields.Str()

    @post_load
    def make(self, data, **kwargs) -> ReweJsonSuborder:
        return ReweJsonSuborder(**data)


class ReweJsonOrderSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    # payments = fields.List()
    # invoiceAddress: object
    orderValue = fields.Integer()
    clientInfo = fields.Str()
    # paymentInfo: object
    subOrders = fields.List(fields.Nested(ReweJsonSuborderSchema,
                                          unkown=EXCLUDE))
    # OrderId = fields.Str()
    creationDate = fields.Str()

    @post_load
    def make(self, data, **kwargs) -> ReweJsonOrder:
        return ReweJsonOrder(**data)


class ReweJsonOrdersListSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    orders = fields.List(fields.Nested(ReweJsonOrderSchema, unkown=EXCLUDE))

    @post_load
    def make(self, data, **kwargs) -> ReweJsonOrdersList:
        return ReweJsonOrdersList(**data)


class ReweJsonSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    # addressData = fields.List()
    # deliveryflats = fields.List()
    # payback: object
    # customerData: object
    # paymentData: object
    orders = fields.Nested(ReweJsonOrdersListSchema, unkown=EXCLUDE)
    # coupons: object

    @post_load
    def make(self, data, **kwargs) -> ReweJson:
        return ReweJson(**data)


def sorted_orders(data: ReweJson) -> list[ReweJsonOrder]:
    return sorted(data.orders.orders,
                  key=lambda x: x.creationDate, reverse=True)


def list_orders(data: ReweJson):
    for i, orde in enumerate(sorted_orders(data)):
        date = orde.creationDate
        value = orde.orderValue
        merchant = orde.subOrders[0].merchant
        print(f'{i+1}. {date[:4]}-{date[4:6]}-{date[6:8]} {merchant}'
              f' {int(value) / 100} €')


def list_rewe_purchases(args, *_) -> None:
    ''' List purchases from REWE

    List purchases from the German supermarket chain REWE
    '''
    list_orders(ReweJsonSchema().load(json.load(args.file)))


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
    rewe = (purchase_store
            .add_parser('rewe',
                        help='German supermarket chain REWE',
                        description='Import from DSGVO provided'
                                    ' "Meine REWE-Shop-Daten.json"')
            .add_subparsers())
    rewe.add_parser('list',
                    help='list the purchases'
                    ).set_defaults(func=list_rewe_purchases)
    purchase.add_argument('file',
                          type=FileType('r', encoding='utf-8'),
                          help='')
    return parser


def import_purchase(args,
                    config: ConfigParser,
                    grocy: GrocyApi):
    ''' help importing multiple purchases into grocy '''
    stores = {'netto': netto_purchase}
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
    config = ConfigParser()
    config.read(join(dirname(abspath(argv[0])), 'config.ini'))
    grocy = GrocyApi(**config['grocy'], dry_run=args.dry_run)
    args.func(args, config, grocy)


if __name__ == '__main__':
    main()
