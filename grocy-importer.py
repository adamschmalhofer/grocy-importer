#!/usr/bin/python3

import re
from sys import argv, exit
from email.parser import Parser
from typing import List, Union, Iterable
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import dirname, abspath, join

from bs4 import BeautifulSoup
import requests


class GrocyApi:

    def __init__(self, api_key, base_url):
        self.HEADERS = {'GROCY-API-KEY': api_key}
        self.BASE_URL = base_url

    def get_all_products(self):
        response = requests.get(self.BASE_URL + '/objects/products',
                                headers=self.HEADERS)
        return {p['name']: p for p in response.json()}

    def purchase(self, productId: int, amount: int, price: str,
                 shopping_location_id: int):
        CALL = f'/stock/products/{productId}/add'
        response = requests.post(self.BASE_URL + CALL,
                                 headers=self.HEADERS,
                                 json={'amount': amount,
                                       'price': price,
                                       'transaction_type': 'purchase',
                                       'shopping_location_id': shopping_location_id
                                       })
        assert(response.status_code/100 == 2)


def cleanup_product_name(orig: str) -> str:
    return re.sub(r'\s+', ' ', orig)


@dataclass
class Purchase:
    amount: Union[int, float]
    price: str
    name: str


def parse_purchase(args):
    return (Purchase(1,
                     from_netto_price(args[1]),
                     cleanup_product_name(args[0]))
            if len(args) == 2
            else Purchase(float(args[0].split()[0]),
                          from_netto_price(args[2]),
                          cleanup_product_name(args[1])))


def from_netto_price(netto_price: str) -> str:
    return netto_price.split()[0].replace(',', '.')


def simplify(items: Iterable[Purchase]) -> List[Purchase]:
    '''
    >>> simplify([parse_purchase(['Milch', '1,00']),
    ... parse_purchase(['Mehl', '2,00'])])
    [Purchase(amount=1, price='2.00', name='Mehl'), Purchase(amount=1, price='1.00', name='Milch')]

    >>> simplify([parse_purchase(['Milch', '1,00']),
    ... parse_purchase(['Milch', '1,00'])])
    [Purchase(amount=2, price='1.00', name='Milch')]
    >>> simplify([parse_purchase(['Milch', '1,00']),
    ... parse_purchase(['Mehl', '2,00']),
    ... parse_purchase(['Milch', '1,00'])])
    [Purchase(amount=1, price='2.00', name='Mehl'), Purchase(amount=2, price='1.00', name='Milch')]
    >>> simplify([parse_purchase(['Punkte-Gutschein', '-1,05'])])
    []

    '''
    return [Purchase(sum(p.amount for p in g),
                     price,
                     name)
            for (name, price), g
            in groupby(sorted(items, key=lambda p: p.name),
                       lambda p: (p.name, p.price))]


def netto_purchase():
    with open(argv[1], 'r', encoding='utf-8') as f:
        email = Parser().parse(f)
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
    items: List[List[str]] = []
    for p in purchase:
        if p.isspace():
            items.append([])
        else:
            items[-1].append(p)
    return simplify(parse_purchase(item) for item in items if len(item) > 1)


def main():
    config = ConfigParser()
    config.read(join(dirname(abspath(argv[0])), 'config.ini'))
    groceries = netto_purchase()
    grocy = GrocyApi(**config['grocy'])
    known_products = grocy.get_all_products()
    while any(unknown_items := [str(item)
                                for item in groceries
                                if item.name not in known_products]):
        print('Unknown products. Please add to grocy:')
        print('\n'.join(unknown_items))
        input('...')
        known_products = grocy.get_all_products()
    for item in groceries:
        p = known_products[item.name]
        grocy.purchase(p['id'],
                       item.amount * float(p['qu_factor_purchase_to_stock']),
                       item.price,
                       config['netto']['shopping_location_id'])
        print(f'Added {item}')


if __name__ == '__main__':
    main()
