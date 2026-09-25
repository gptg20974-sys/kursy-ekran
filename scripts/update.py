#!/usr/bin/env python3
"""Refresh the public dashboard data from primary sources."""
import datetime as dt
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data.json'
NOW = dt.datetime.now(dt.timezone.utc)

def request(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'MarketScreen/1.0 (+public information display)'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()

def num(value):
    return float(value.replace(' ', '').replace(',', '.'))

def rate_xml(payload):
    root = ET.fromstring(payload)
    values = {}
    for item in root.findall('Valute'):
        code = item.findtext('CharCode')
        if code in {'USD', 'EUR', 'JPY'}:
            values[code] = num(item.findtext('Value')) / int(item.findtext('Nominal'))
    return root.attrib.get('Date'), values

def rates():
    today, a = rate_xml(request('https://www.cbr.ru/scripts/XML_daily.asp'))
    yesterday = (NOW - dt.timedelta(days=1)).strftime('%d/%m/%Y')
    prior_day, b = rate_xml(request('https://www.cbr.ru/scripts/XML_daily.asp?date_req=' + yesterday))
    out = {'date': today}
    for code in ('USD', 'JPY', 'EUR'):
        value = a.get(code)
        if value is not None:
            change = value - b[code] if today != prior_day and code in b else None
            out[code] = {'value': value, 'change': change, 'percent': change / b[code] * 100 if change is not None else None}
    return out

def rows(table):
    return [dict(zip(table['columns'], values)) for values in table['data']]

def brent():
    url = ('https://iss.moex.com/iss/engines/futures/markets/forts/securities.json'
           '?iss.meta=off&iss.only=securities,marketdata'
           '&securities.columns=SECID,SHORTNAME,ASSETCODE,LASTTRADEDATE,PREVPRICE'
           '&marketdata.columns=SECID,LAST,TRADEDATE,TIME')
    data = json.loads(request(url))
    market = {item['SECID']: item for item in rows(data['marketdata'])}
    contracts = sorted((item for item in rows(data['securities'])
                        if item.get('ASSETCODE') == 'BR' and item['LASTTRADEDATE']
                        and item['LASTTRADEDATE'] >= NOW.strftime('%Y-%m-%d')),
                       key=lambda item: item['LASTTRADEDATE'])
    for contract in contracts:
        quote = market.get(contract['SECID'])
        if quote and quote.get('LAST') is not None and float(quote['LAST']) > 0:
            value = float(quote['LAST'])
            previous = contract.get('PREVPRICE')
            change = value - float(previous) if previous else None
            print('Brent:', contract['SECID'], value, quote.get('TRADEDATE'), quote.get('TIME'))
            return {'value': value, 'change': change,
                    'percent': change / float(previous) * 100 if change is not None else None,
                    'contract': contract['SHORTNAME'], 'secid': contract['SECID'],
                    'tradeDate': quote.get('TRADEDATE'), 'tradeTime': quote.get('TIME')}
    raise RuntimeError('MOEX returned no traded, unexpired Brent contracts')

def weather():
    url = ('https://api.open-meteo.com/v1/forecast?latitude=55.7558&longitude=37.6173'
           '&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m'
           '&timezone=Europe%2FMoscow')
    value = json.loads(request(url))['current']
    return {'temperature': value['temperature_2m'], 'feels': value['apparent_temperature'],
            'code': value['weather_code'], 'wind': value['wind_speed_10m']}

def news():
    root = ET.fromstring(request('https://rssexport.rbc.ru/rbcnews/news/30/full.rss'))
    items = []
    for item in root.findall('./channel/item')[:10]:
        title, link = (item.findtext('title') or '').strip(), (item.findtext('link') or '').strip()
        if title:
            items.append({'title': title, 'link': link if link.startswith('https://www.rbc.ru/') else 'https://www.rbc.ru/'})
    return items

def main():
    data = {'rates': None, 'brent': None, 'weather': None, 'news': [], 'fetchedAt': NOW.isoformat()}
    for key, fn in [('rates', rates), ('brent', brent), ('weather', weather), ('news', news)]:
        try:
            data[key] = fn()
        except Exception as exc:
            print(f'{key}: unavailable: {exc}')
    if not any((data['rates'], data['brent'], data['weather'], data['news'])):
        raise RuntimeError('No data source responded; existing data file remains untouched')
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print('Updated:', ', '.join(k for k in ('rates', 'brent', 'weather', 'news') if data[k]))

if __name__ == '__main__':
    main()
