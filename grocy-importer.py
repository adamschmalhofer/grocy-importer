#!/usr/bin/python3

from sys import argv
from email.parser import Parser
from typing import List, Union
from dataclasses import dataclass
from bs4 import BeautifulSoup


@dataclass
class Purchase:
    amount: Union[int, float]
    price: str
    name: str

    def __init__(self, args):
        if len(args) == 2:
            self.name = args[0]
            self.price = from_netto_price(args[1])
            self.amount = 1
        else:
            self.name = args[1]
            self.price = from_netto_price(args[2])
            self.amount = float(args[0].split()[0])


def from_netto_price(netto_price: str) -> str:
    return netto_price.split()[0].replace(',', '.')


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
                                            'DeutschlandCard'])
                for column in row.select('td')
                if column.get_text() != ''
                )
items: List[List[str]] = []
for p in purchase:
    if p.isspace():
        items.append([])
    else:
        items[-1].append(p)
print([Purchase(item) for item in items if len(item) > 1])
