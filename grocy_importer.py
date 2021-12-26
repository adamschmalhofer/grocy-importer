#!/usr/bin/python3

''' Help importing into Grocy '''

from argparse import ArgumentParser, FileType
import re
from sys import argv
from email.parser import Parser
from typing import Union, Iterable, TextIO
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import dirname, abspath, join

from bs4 import BeautifulSoup
import requests


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

    def purchase(self, product_id: int, amount: int, price: str,
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


def netto_purchase(file: TextIO):
    ''' Import from Netto Marken-Discount

    Import a "digitaler Kassenbon" email from the german discount
    supermarket chain Netto Marken-Discount
    '''
    email = Parser().parse(file)
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


def get_argparser() -> ArgumentParser:
    ''' ArgumentParser factory method '''
    parser = ArgumentParser(description='Help importing into Grocy')
    parser.add_argument('--dry-run', action='store_true',
                        help='perform a trial run with no changes made')
    subparsers = parser.add_subparsers()
    purchase = subparsers.add_parser('purchase',
                                     help='import purchases')
    purchase.set_defaults(func=import_purchase)
    purchase_store = purchase.add_subparsers(metavar='STORE',
                                             required=True,
                                             dest='store')
    purchase_store.add_parser('netto',
                              help='import a "digitaler Kassenbon" email from'
                                   ' the german discount supermarket chain'
                                   ' Netto Marken-Discount')
    purchase.add_argument('file',
                          type=FileType('r', encoding='utf-8'))
    return parser


def import_purchase(args,
                    config: ConfigParser,
                    grocy: GrocyApi):
    ''' help importing multiple purchases into grocy '''
    groceries = netto_purchase(args.file)
    known_products = grocy.get_all_products()
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
                       int(config[args.store]['shopping_location_id'])
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
