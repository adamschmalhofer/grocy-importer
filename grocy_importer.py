#!/usr/bin/python3

''' Help importing into Grocy '''

import re
from sys import argv
from email.parser import Parser
from typing import Union, Iterable
from dataclasses import dataclass
from itertools import groupby
from configparser import ConfigParser
from os.path import dirname, abspath, join

from bs4 import BeautifulSoup
import requests


class GrocyApi:
    ''' Calls to the Grocy REST-API '''

    def __init__(self, api_key, base_url):
        self.headers = {'GROCY-API-KEY': api_key}
        self.base_url = base_url

    def get_all_products(self):
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers)
        return {p['name']: p for p in response.json()}

    def purchase(self, product_id: int, amount: int, price: str,
                 shopping_location_id: int):
        ''' Add a purchase to grocy '''
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


def netto_purchase():
    ''' import a 'digitaler Kassenbon' email '''
    with open(argv[1], 'r', encoding='utf-8') as fil:
        email = Parser().parse(fil)
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


def main():
    ''' Run the CLI program '''
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
        pro = known_products[item.name]
        grocy.purchase(pro['id'],
                       item.amount * float(pro['qu_factor_purchase_to_stock']),
                       item.price,
                       config['netto']['shopping_location_id'])
        print(f'Added {item}')


if __name__ == '__main__':
    main()
