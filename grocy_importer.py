#!/usr/bin/python3

''' Help importing into and from Grocy '''

from __future__ import annotations

from argparse import ArgumentParser, FileType
import re
from abc import (ABC, abstractmethod)
from email.parser import Parser
from typing import (Union, Iterable, Mapping, Optional, TextIO, TypedDict,
                    Literal, Callable, cast, Any, NotRequired, Tuple)
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
from shutil import copyfile
import yaml

from bs4 import BeautifulSoup
import requests
from marshmallow import Schema, fields, EXCLUDE, post_load
from appdirs import user_config_dir
import argcomplete
from pdfminer.high_level import extract_text
from recipe_scrapers import scrape_me


logger = getLogger(__name__)

GrocyDateTime = str    # 'yyyy-mm-dd HH:MM:SS' or 'yyyy-mm-dd'


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


class AppConfig(TypedDict):
    ''' Structure of our config.ini '''
    grocy: AppConfigGrocySection
    netto: NotRequired[AppConfigPurchaseSection]
    rewe: NotRequired[AppConfigPurchaseSection]
    dm: NotRequired[AppConfigPurchaseSection]


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


class GrocyChoreFull(TypedDict):
    ''' A chore as returned from Grocy API via /object '''
    id: int
    name: str
    rescheduled_date: NotRequired[Optional[GrocyDateTime]]
    description: Optional[str]


class GrocyChore(TypedDict):
    ''' A chore as returned from the Grocy API via /chore '''
    id: int
    chore_name: str
    description: Optional[str]
    rescheduled_date: NotRequired[Optional[GrocyDateTime]]


def as_chore_completed(orig: GrocyChore) -> GrocyChoreCompleted:
    return GrocyChoreCompleted({"chore_id": orig['id'],
                                "tracked_time": (datetime.now()
                                                 .strftime('%Y-%m-%d'))})


class GrocyChoreCompleted(TypedDict):
    ''' A chore as returned from Grocy API via /chores/.../execute '''
    chore_id: int
    tracked_time: GrocyDateTime


def as_chore_full(orig: GrocyChore,
                  rescheduled_date: Optional[GrocyDateTime] = None
                  ) -> GrocyChoreFull:
    return GrocyChoreFull({'id': orig['id'], 'name': orig['chore_name'],
                           'description': orig['description'],
                           'rescheduled_date': rescheduled_date})


class GrocyUserFields(TypedDict):
    ''' Grocy UserFields we use '''
    context: NotRequired[Optional[str]]
    prio: NotRequired[Optional[str]]
    project: NotRequired[Optional[str]]


class GrocyErrorResponse(TypedDict):
    ''' Grocy Error Reponse '''
    error_message: str


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

    def assert_valid_response(self, response: requests.Response) -> None:
        if response.status_code//100 != 2:
            try:
                error_message = cast(GrocyErrorResponse,
                                     response.json())['error_message']
                raise UserError('Connection to Grocy failed with'
                                f' {response.reason}: {error_message}')
            except requests.exceptions.JSONDecodeError:
                raise UserError('Connection to Grocy failed:'
                                f' {response.reason}')

    def get_all_product_barcodes(self) -> dict[str, GrocyProductBarCode]:
        ''' all product barcodes known to grocy '''
        response = requests.get(self.base_url + '/objects/product_barcodes',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return {p['barcode']: p for p in response.json()}

    def get_all_products(self) -> dict[str, GrocyProduct]:
        ''' all products known to grocy '''
        response = requests.get(self.base_url + '/objects/products',
                                headers=self.headers,
                                params=self.only_active,
                                timeout=self.timeout)
        self.assert_valid_response(response)
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
        self.assert_valid_response(response)
        return {p['id']: p for p in response.json()}

    def get_all_product_groups(self) -> dict[int, GrocyProductGroup]:
        ''' all product groups known to grocy '''
        response = requests.get(self.base_url + '/objects/product_groups',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return {p['id']: p for p in response.json()}

    def get_all_shopping_locations(self) -> Iterable[GrocyShoppingLocation]:
        ''' all shopping locations known to grocy '''
        response = requests.get(self.base_url + '/objects/shopping_locations',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(Iterable[GrocyShoppingLocation], response.json())

    def get_location_names(self) -> Mapping[int, str]:
        ''' all (storage) locations known to grocy '''
        response = requests.get(self.base_url + '/objects/locations',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return {location['id']: location['name']
                for location in cast(Iterable[GrocyLocation], response.json())}

    def get_all_quantity_units(self) -> Iterable[GrocyQuantityUnit]:
        ''' all quantity units known to grocy '''
        response = requests.get(self.base_url + '/objects/quantity_units',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(Iterable[GrocyQuantityUnit], response.json())

    def get_all_quantity_units_by_id(self) -> dict[int, GrocyQuantityUnit]:
        ''' all quantity units known to grocy '''
        response = requests.get(self.base_url + '/objects/quantity_units',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return {p['id']: p for p in response.json()}

    def get_all_quantity_unit_convertions(self
                                          ) -> Iterable[GrocyQUnitConvertion]:
        ''' all quantity unit convertions known to grocy '''
        response = requests.get(self.base_url
                                + '/objects/quantity_unit_conversions',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(Iterable[GrocyQUnitConvertion], response.json())

    def get_all_shopping_list(self) -> Iterable[GrocyShoppingListItem]:
        ''' all items on shopping lists '''
        response = requests.get(self.base_url
                                + '/objects/shopping_list',
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(Iterable[GrocyShoppingListItem], response.json())

    def get_overdue_chores(self, now: datetime) -> Iterable[GrocyChore]:
        ''' all chores that are overdue '''
        params = {'query[]': ['next_estimated_execution_time<'
                              + now.strftime('%F %T')],
                  'order': 'next_estimated_execution_time'}
        response = requests.get(self.base_url
                                + '/chores',
                                headers=self.headers,
                                params=params,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(Iterable[GrocyChore], response.json())

    def get_scheduled_manual_chores(self, now: datetime, get_all: bool = False
                                    ) -> Iterable[GrocyChoreFull]:
        ''' all manual chores that are scheduled '''
        params = {'query[]': (['period_type=manually',
                               'active=1',
                               'rescheduled_date>'
                               + now.strftime('%F %T')
                               ]
                              if not get_all
                              else ['active=1']),
                  'order': 'rescheduled_date'}
        response = requests.get(f'{self.base_url}/objects/chores',
                                headers=self.headers,
                                params=params,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(Iterable[GrocyChoreFull], response.json())

    def schedule_chore(self, chore_id: int, date_time: GrocyDateTime
                       ) -> None:
        if self.dry_run:
            return
        data = {'rescheduled_date': date_time}
        response = requests.put(f'{self.base_url}/objects/chores/{chore_id}',
                                headers=self.headers,
                                json=data,
                                timeout=self.timeout)
        self.assert_valid_response(response)

    def did_chore(self, chore_id: int, tracked_time: Optional[str],
                  skip: bool = False,
                  ) -> GrocyChoreCompleted:
        ''' Mark a chore as done '''
        if self.dry_run:
            ret = self.get_chore(chore_id)
            return GrocyChoreCompleted({"chore_id": ret['id'],
                                        "tracked_time":
                                            (datetime.now()
                                             .strftime('%Y-%m-%d'))})
        data = ({}
                if tracked_time is None
                else {'tracked_time': tracked_time,
                      'done_by': 0, 'skipped': skip})
        logger.debug(data)
        response = requests.post(f'{self.base_url}/chores/{chore_id}/execute',
                                 headers=self.headers,
                                 json=data,
                                 timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(GrocyChoreCompleted, response.json())

    def charge_battery(self, battery_id: int, tracked_time: Optional[str]
                       ) -> None:
        ''' Mark a chore as done '''
        if self.dry_run:
            return
        data = ({}
                if tracked_time is None
                else {'tracked_time': tracked_time})
        logger.debug(data)
        response = requests.post(f'{self.base_url}/batteries'
                                 f'/{battery_id}/charge',
                                 headers=self.headers,
                                 json=data,
                                 timeout=self.timeout)
        self.assert_valid_response(response)

    def get_chore(self, chore_id: int) -> GrocyChoreFull:
        ''' Get a chore from grocy '''
        url = f'{self.base_url}/chores/{chore_id}'
        response = requests.get(url,
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(GrocyChoreFull, response.json()["chore"])

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
        self.assert_valid_response(response)

    def get_user_fields(self, entity: str, object_id: int) -> GrocyUserFields:
        ''' Gets a Grocy user field '''
        call = f'/userfields/{entity}/{object_id}'
        response = requests.get(self.base_url + call,
                                headers=self.headers,
                                timeout=self.timeout)
        self.assert_valid_response(response)
        return cast(GrocyUserFields, response.json())

    def set_userfields(self, entity: str, object_id: int,
                       user_fields: dict[str, object]) -> None:
        ''' Sets a Grocy user field '''
        call = f'/userfields/{entity}/{object_id}'
        response = requests.put(self.base_url + call,
                                headers=self.headers,
                                timeout=self.timeout,
                                data=json.dumps(user_fields))
        self.assert_valid_response(response)


@dataclass
class AppArgs:
    ''' Common args '''
    dry_run: bool
    timeout: int
    ids: list[int]
    func: Callable[[AppArgs, AppConfig, GrocyApi], None]
    context: Optional[str]
    due_deadline: datetime
    all: bool


@dataclass
class CliArgs(AppArgs):
    ''' Structure of our CLI args '''
    regex: str
    store: Literal['netto', 'rewe']
    file: TextIO
    file_path: str
    order: int
    url: str
    show: bool
    skip: bool
    days: int
    at: Optional[GrocyDateTime]
    keep: Literal['later', 'earlier', 'old', 'new']
    entity: str


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
    price: float    # total
    name: str


def simplify(items: Iterable[Purchase]
             ) -> list[Purchase]:
    '''
    >>> n = Netto()
    >>> simplify([n._parse_purchase(['Milch', '1,00']),
    ...           n._parse_purchase(['Mehl', '2,00'])])
    ... #doctest: +NORMALIZE_WHITESPACE
    [Purchase(amount=1, price=2.0, name='Mehl'),
     Purchase(amount=1, price=1.0, name='Milch')]

    >>> simplify([n._parse_purchase(['Milch', '1,00']),
    ...           n._parse_purchase(['Milch', '1,00'])])
    [Purchase(amount=2, price=1.0, name='Milch')]
    >>> simplify([n._parse_purchase(['Milch', '1,00']),
    ...           n._parse_purchase(['Mehl', '2,00']),
    ...           n._parse_purchase(['Milch', '1,00'])])
    ... #doctest: +NORMALIZE_WHITESPACE
    [Purchase(amount=1, price=2.0, name='Mehl'),
     Purchase(amount=2, price=1.0, name='Milch')]
    >>> simplify([n._parse_purchase(['Punkte-Gutschein', '-1,05'])])
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
            if self.store_info.use_file_path:
                subcommand.add_argument('file_path',
                                        type=str,
                                        metavar='file',
                                        help=self.store_info.file_help_msg)
            else:
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
    use_file_path: bool = False


class Rewe(Store):
    'Liefer- and Abholservice of the German supermarket chain REWE'

    @property
    def store_info(self) -> StoreSubcommandInfo:
        return StoreSubcommandInfo(
            'rewe',
            'Import from DSGVO provided "Meine REWE-Shop-Daten.json"',
            '''
            Path to "Meine REWE-Shop-Daten.json" file. Downloadable from
            https://shop.rewe.de/mydata/privacy under "Meine Daten anfordern".
            This only includes purches that were made via the Liefer- or
            Abholservice. For in store purchases see ebon.
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


class Ebon(Store):
    'The receipt as PDF from diffent German stores (dm, Netto, or Rewe)'

    @property
    def store_info(self) -> StoreSubcommandInfo:
        return StoreSubcommandInfo(
                'ebon',
                '''
                Import a "Kassenbon als PDF" downloadable from webpage under
                "Meine Markt-Einkäufe" for dm. In the store you will have to
                show the Kundenkarte via the dm-App.
                ''',
                'Path to pdf',
                use_file_path=True
                )

    def get_purchase(self, args: CliArgs) -> list[Purchase]:
        return list(self._get_purchases(extract_text(args.file_path)))

    @staticmethod
    def _get_purchases(ebon: str) -> Iterable[Purchase]:
        r'''

        >>> list(Ebon._get_purchases(
        ... """15.03.2023  15:40  3022/2  288904/2   5166
        ...
        ... dmBio Streichcr. Curry PM 180g     1,45  2
        ...
        ... CD Deo Roll-on Bio Granatapfel     1,95  1
        ...
        ... SUMME EUR                          3,40
        ...
        ... AMEX EUR                          -3,40
        ...
        ... MwSt-Satz       Brutto     Netto      MwSt
        ... """))
        ... #doctest: +NORMALIZE_WHITESPACE
        [Purchase(amount=1, price=1.45, name='dmBio Streichcr. Curry PM 180g'),
         Purchase(amount=1, price=1.95, name='CD Deo Roll-on Bio Granatapfel')]
        >>> list(Ebon._get_purchases(
        ... """09.02.2023  18:24  3022/1  328288/3   2656
        ...
        ... Kodak Artikel Sofort               0,10  1
        ...
        ... 4x 1,25 dmBio Milch 1,5% 1L        5,00  2
        ...
        ... 2x 1,95 Dental Delight ZC Pola     3,90  1
        ...
        ... SUMME EUR                          9,00
        ... """))
        ... #doctest: +NORMALIZE_WHITESPACE
        [Purchase(amount=1, price=0.1, name='Kodak Artikel Sofort'),
         Purchase(amount=4, price=5.0, name='dmBio Milch 1,5% 1L'),
         Purchase(amount=2, price=3.9, name='Dental Delight ZC Pola')]
        '''
        regex = re.compile(r'^(?:(\d+)x \d+,\d\d\s+)?(.*?)\s+'
                           r'(\d+,\d\d)\s+[12]')
        for line in ebon.splitlines()[1:]:
            if line.startswith('SUMME '):
                break
            if len(line) == 0:
                continue
            match_ = regex.search(line)
            assert match_ is not None
            yield Purchase(int(match_.group(1) or 1),
                           float(match_.group(3).replace(',', '.')),
                           match_.group(2))


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
        match_ = re.search(r'^\s*(¼|½|¾|\d+(?:\s+(?:\-\s+\d+|½))?)'
                           r'(?:\s+(\S*[^\s,]))?'
                           r'(?:\s+([^,(]*[^,(\s]).*)$',
                           text)
        if match_ is None:
            return UnparseableIngredient(text)
        return Ingredient(match_.group(1),
                          match_.group(2) or '',
                          match_.group(3) or '',
                          match_.group(0))


def recipe_ingredients(url: str, timeout: int
                       ) -> list[Union[Ingredient, UnparseableIngredient]]:
    ''' Find all ingrediant of the recipe '''
    scrapper = scrape_me(url, timeout=timeout, wild_mode=True)
    ingredients = [Ingredient.parse(normanlize_white_space(item)
                                    )
                   for item in scrapper.ingredients()]
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
    ''' Convert ingredients from the store into our grocy names and units
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
        ''' Normalize given ingredients with grocy '''
        product_known = []
        product_unknown: list[Union[Ingredient, UnparseableIngredient]] = []
        grocy_products = {n.lower(): p for (n, p) in self.products.items()}
        for ingred in ingredients:
            if isinstance(ingred, UnparseableIngredient):
                product_unknown.append(ingred)
            elif (ingred.name.lower() not in grocy_products
                  and ingred.name != ''):
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
                              and not any(grocy_products[ingred.name
                                                         ]['qu_id_stock']
                                          == u['id']
                                          for u in units)
                              and not any(u['id'] == c['from_qu_id']
                                          and c['to_qu_id']
                                          == grocy_products[ingred.name.lower()
                                                            ]['qu_id_stock']
                                          and c['product_id'
                                                ] in [grocy_products[ingred
                                                                     .name
                                                                     .lower()
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
    ingredients = recipe_ingredients(args.url, args.timeout)
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


def battery_charge_cmd(args: CliArgs,
                       _: AppConfig,
                       grocy: GrocyApi) -> None:
    ''' Track battery charge cycle. '''
    for battery_id in args.ids:
        grocy.charge_battery(battery_id, args.at)


def chore_did_cmd(args: CliArgs,
                  _: AppConfig,
                  grocy: GrocyApi) -> None:
    ''' Mark chore(s) as done.
    '''
    if len(args.ids) > 0:
        for chore_id in args.ids:
            grocy.did_chore(chore_id, args.at, args.skip)
        return
    now = datetime.now()
    if not args.all:
        for chore in grocy.get_overdue_chores(now):
            if human_agrees(f'Completed {chore["chore_name"]}?'):
                grocy.did_chore(chore['id'], args.at, args.skip)
    for choreFull in grocy.get_scheduled_manual_chores(now, args.all):
        if human_agrees(f'Completed {choreFull["name"]}?'):
            grocy.did_chore(chore['id'], args.at, args.skip)


def chore_schedule_cmd(args: CliArgs,
                       _: AppConfig,
                       grocy: GrocyApi) -> None:
    ''' Schedule chore(s).
    '''
    at = args.at or (datetime.now() + timedelta(days=args.days)
                     ).strftime('%Y-%m-%d %H:%M:%S')
    for chore_id in args.ids:
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


def in_context(chores: Iterable[GrocyChore], context: Optional[str]
               ) -> Iterable[GrocyChore]:
    if context is None:
        return chores
    regex = given_context_or_no_context_regex(context)
    return (c
            for c in chores
            if regex.search(c['chore_name']) is not None)


def given_context_or_no_context_regex(context: str) -> re.Pattern[str]:
    '''
        >>> regex = given_context_or_no_context_regex('home')
        >>> regex.search('@chore starting with context')
        >>> regex.search('chore ending with @context')
        >>> regex.search('chore with @context in the middle')
        >>> regex.search('chore without any context') is not None
        True
        >>> regex.search('@home chore starting with context') is not None
        True
        >>> regex.search('chore ending with context @home') is not None
        True
        >>> regex.search('chore with @home context in the middle') is not None
        True
        >>> regex.search('chore with @home and other @context') is not None
        True
        >>> regex.search('chore with email@example.com and no context'
        ...              ) is not None
        True
        >>> regex.search('chore with multible non-@context at symbols'
        ...              ' email@example.com'
        ...              ) is not None
        True
    '''
    literal_context = re.escape(context)
    return re.compile(rf'{literal_context}|^[^@]*([^ ]@[^@]*)*$')


def todotxt_chore_pull(args: TodotxtArgs,
                       config: AppConfig,
                       grocy: GrocyApi) -> None:
    '''Replace chores in todo.txt with current ones from grocy'''
    todo_file = args.environ.TODO_FILE
    new_content = []
    regex = re.compile(r'chore:(\d+)')
    with open(todo_file, 'r') as f:
        for line in f:
            match_ = regex.search(line)
            if match_ is None:
                new_content.append(line)
            elif line.startswith('x '):
                raise UserError(f'chore {match_.group(1)} is marked'
                                ' as done in todo.txt.\n'
                                ' Run "push" and "archive" first. Aborting.')
    copyfile(todo_file, todo_file + ".bak")
    with open(todo_file, 'w') as f:
        for line in new_content:
            f.write(line)
        chore_show_cmd(args, config, grocy, f)


def todotxt_chore_push(args: TodotxtArgs,
                       _: AppConfig,
                       grocy: GrocyApi) -> None:
    ''' Send completed and rescheduled_date chores in todo.txt to grocy '''
    time = datetime.now().strftime('%H:%M:%S')
    regex = re.compile(r'^x (\d{4}-\d{2}-\d{2}) (?:.* )?\+auto '
                       r'|^x (\d{4}-\d{2}-\d{2}) (?:.* )?chore:(\d+)'
                       r'|chore:(\d+) (?:.* )?t:(\d{4}-\d{2}-\d{2})'
                       r'|^\(S\) (?:.* )?chore:(\d+)')
    with open(args.environ.TODO_FILE, 'r') as f:
        for line in f:
            match_ = regex.search(line)
            if match_ is None or match_.group(1) is not None:
                continue
            if match_.group(2) is not None:
                did_at: GrocyDateTime = f'{match_.group(2)} {time}'
                response = grocy.did_chore(int(match_.group(3)),
                                           tracked_time=did_at)
                print(f'Completed {response["chore_id"]}'
                      f' on {response["tracked_time"]}')
            elif match_.group(4) is not None:
                grocy.schedule_chore(int(match_.group(4)),
                                     f'{match_.group(5)}')
                print(f'Rescheduled {match_.group(4)}'
                      f' to {match_.group(5)}')
            else:
                did_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                response = grocy.did_chore(int(match_.group(6)),
                                           tracked_time=did_at)
                print(f'Skiped {response["chore_id"]}'
                      f' on {response["tracked_time"]}')


def userfield_cmd(args: CliArgs,
                  _: AppConfig,
                  grocy: GrocyApi) -> None:
    ''' Quickly add userfields '''
    try:
        for item in yaml.safe_load(args.file):
            try:
                item_id = item['id']
                del item['id']
                grocy.set_userfields(args.entity, item_id, item)
                print(f'{args.entity} {item_id}')
            except KeyError:
                print('Error: missing id-field for entity in yaml file.',
                      file=sys.stderr)
    except TypeError:
        print('Error: list missing in yaml file.', file=sys.stderr)
    except yaml.scanner.ScannerError:
        print('Error: yaml invalid.', file=sys.stderr)


def chore_show_cmd(args: AppArgs,
                   _: AppConfig,
                   grocy: GrocyApi,
                   outfile: TextIO = sys.stdout) -> None:
    ''' Show chore(s).
    '''
    if len(args.ids) > 0:
        for chore_id in args.ids:
            choreFull = grocy.get_chore(chore_id)
            print(choreFull["name"],
                  file=outfile)
            fields = grocy.get_user_fields('chores', choreFull["id"])
            if (outfile is sys.stdout
                    and choreFull["description"] is not None):
                print("---")
                print(choreFull["description"])
            if (outfile is sys.stdout and fields is not None):
                print("---")
                print(yaml.dump(fields))
                print()
        return
    if not args.all:
        for chore in in_context(grocy.get_overdue_chores(args.due_deadline),
                                args.context):
            print(' '.join(show_chore(chore['id'],
                                      chore['chore_name'],
                                      )),
                  file=outfile)
    for choreFull in grocy.get_scheduled_manual_chores(args.due_deadline,
                                                       args.all):
        print(' '.join(show_chore(choreFull['id'],
                       choreFull['name'],
                       choreFull['rescheduled_date'])),
              file=outfile)


def has_userfield(name: Literal['context', 'prio', 'project'],
                  fields: GrocyUserFields
                  ) -> bool:
    try:
        return fields[name] is not None
    except (KeyError, TypeError):
        return False


def show_chore(chore_id: int, chore_name: str,
               chore_rescheduled_date: Optional[str] = None
               ) -> Iterable[str]:
    yield chore_name
    if chore_rescheduled_date is not None:
        yield f'due:{chore_rescheduled_date.split(" ")[0]}'
    yield f'chore:{chore_id}'


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


def add_common_arguments(parser: ArgumentParser) -> None:
    parser.add_argument('--timeout', metavar='N', default=10, type=int,
                        help='Override the default timeout for each REST call')
    parser.add_argument('--dry-run', action='store_true',
                        help='perform a trial run with no changes made')


def add_chore_show_arguments(parser: ArgumentParser) -> None:
    parser.add_argument('ids', type=int, nargs='*')
    parser.add_argument('--context', '-@', type=str, nargs='?',
                        help="Show chores with given context or no context"
                        )
    parser.add_argument('--all', action='store_true',
                        help='Show all (active) chores. By default we only'
                             ' show manually scheduled and overdue chores.')
    parser.add_argument('--due-today', action='store_const',
                        const=datetime.now().date() + timedelta(days=1),
                        dest='due_deadline', default=datetime.now(),
                        help='Show chores that are overdue today'
                             ' (instead of now)')


@dataclass
class TodotxtEnvVariables:
    TODO_FULL_SH: str
    TODO_FILE: str


@dataclass
class GrocyEnvVariables:
    GROCY_API_KEY: str
    GROCY_BASE_URL: str


def get_todotxt_parser(environ: TodotxtEnvVariables) -> ArgumentParser:
    ''' ArgumentParser factory method for todo.txt plugin '''
    parser = ArgumentParser(description='Interact with Grocy chores')
    parser.set_defaults(environ=environ)
    add_common_arguments(parser)
    toplevel = parser.add_subparsers()
    chore = toplevel.add_parser('chore')
    add_common_arguments(chore)
    chore.set_defaults(func=lambda _, __, ___: chore.print_help())
    subparsers = chore.add_subparsers()
    chore_show = subparsers.add_parser('ls', help='List chores from grocy')
    chore_show.set_defaults(func=chore_show_cmd)
    add_chore_show_arguments(chore_show)

    chore_push = subparsers.add_parser('push',
                                       help='Send completed and rescheduled'
                                            ' chores in todo.txt to grocy')
    chore_push.set_defaults(func=todotxt_chore_push)

    chore_pull = subparsers.add_parser('pull',
                                       help='Replace chores in todo.txt with'
                                            ' current ones from grocy')
    chore_pull.set_defaults(func=todotxt_chore_pull)
    add_chore_show_arguments(chore_pull)

    usage = toplevel.add_parser('usage')
    usage.set_defaults(func=lambda _, __, ___: chore.print_help())
    return parser


def get_argparser_cli(stores: Iterable[Store]) -> ArgumentParser:
    ''' ArgumentParser factory method '''
    parser = ArgumentParser(description='Help importing into Grocy')
    add_common_arguments(parser)
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
    chore_did.add_argument('ids', type=int, nargs='*',
                           help='id of the chore in grocy')
    chore_did.add_argument('--skip', action='store_true')
    chore_did.add_argument('--at',
                           metavar='y-m-d h:m:s',
                           help="Time the chore was done in Grocy's time"
                                " format. E.g. '2022-11-01 08:41:00',")
    chore_schedule = chore.add_parser('schedule',
                                      help='Schedule a chore')
    chore_schedule.set_defaults(func=chore_schedule_cmd)
    chore_schedule.add_argument('ids', type=int, nargs='+',
                                help='id of the chore in grocy')
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
    add_chore_show_arguments(chore_show)
    userfield = subparsers.add_parser('userfield',
                                      description='Add userfield(s) to'
                                                  ' (usally) many grocy'
                                                  ' entities from a yaml'
                                                  ' file.',
                                      help='Quickly add userfields')
    userfield.set_defaults(func=userfield_cmd)
    userfield.add_argument('entity',
                           help='the type of entity that the user fields'
                                ' should be added to. E.g. batteries, chores,'
                                ' chores_log, ...')
    userfield.add_argument('file',
                           type=FileType('r', encoding='utf-8'),
                           help='a yaml file with the user fields to set')
    battery = subparsers.add_parser('battery',
                                    help='Track battery charge cycles'
                                    ).add_subparsers()
    battery_charge = battery.add_parser('charge',
                                        help='Track battery charge cycle')
    battery_charge.add_argument('ids', type=int, nargs='+',
                                help='id of the battery in grocy')
    battery_charge.add_argument('--at',
                                metavar='y-m-d h:m:s',
                                help="Time the battery was charged in Grocy's"
                                     " time format. E.g."
                                     " '2022-11-01 08:41:00',")
    battery_charge.set_defaults(func=battery_charge_cmd)
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
    except IndexError as ex:
        raise UserError(f'No convertion found for {from_qu_id} to {to_qu_id}'
                        f' for {product_id}') from ex


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


def load_config() -> Tuple[AppConfig, str]:
    try:
        return (AppConfig({'grocy':
                          AppConfigGrocySection({'base_url':
                                                 environ['GROCY_BASE_URL'],
                                                 'api_key':
                                                 environ['GROCY_API_KEY']})}),
                '$environ')
    except KeyError:
        config_path = join(user_config_dir('grocy-importer', 'adaschma.name'),
                           'config.ini')
        config_parser = ConfigParser()
        config_parser.read(config_path)
        return (cast(AppConfig, config_parser), config_path)


def main() -> None:
    ''' Run the CLI program '''
    argparser = get_argparser([Netto(), Rewe(), Ebon()])
    argcomplete.autocomplete(argparser)
    args = cast(AppArgs, argparser.parse_args())
    config, config_path = load_config()
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
