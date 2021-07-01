import os
from datetime import datetime
from flask import Flask, request, abort
# from flask_sqlalchemy import SQLAlchemy
import psycopg2

from linebot import (
  LineBotApi, WebhookHandler
)

from linebot.exceptions import (
  InvalidSignatureError
)

from linebot.models import (
  MessageEvent, TextMessage, TextSendMessage
)

DATABASE_URL = os.environ['DATABASE_URL']
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ['CHANNE_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['CHANNEL_SECRET'])

@app.route('/callback', methods=['POST'])
def callback():
  # get X-Line-Signature header value
  signature = request.headers['X-Line-Signature']

  # get request body as text
  body = request.get_data(as_text=True)
  app.logger.info('request body', body)

  # handle webhook body
  try:
    handler.handle(body, signature)
  except InvalidSignatureError:
    print('Invalid signature. Please check your channel access token/secret.')
  return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
  message = event.message.text.lower()
  reply_token = event.reply_token
  response = message
  tokens = message.split()
  token_count = len(tokens)

  if not (tokens[0].startswith('bento') or tokens[0].startswith('便當')):
    return bot_reply(response)
    
  if token_count == 1:
    return bot_reply(reply_token, get_usage())
  if token_count == 2:
    restaurant = tokens[1]
    if restaurant == 'what':
      bucket_list = [r[0] for r in get_bucket_list()]
      return bot_reply(reply_token, 'Some options for you: {}'.format(', '.join(bucket_list)))
    elif restaurant == 'total':
      total = __get_first_row('SELECT SUM(price) FROM bentos;', ())
      bento_count = get_bento_count()
      return bot_reply(reply_token, 'You have spent ${} in total on {} lunch bentos during quarantine!'.format(total, bento_count)) 
    else: # check frequency
      freq = check_frequency(restaurant)
      return bot_reply(reply_token, 'You ordered from {} {} times during quarantine!'.format(restaurant, freq))
  
  restaurant, option = tokens[1:3]
  if token_count == 3:
  # check last order date
    if option.lower() == 'when':
      last_order = check_last_order(restaurant)
      if last_order:
        last_time, items, price = last_order[0]
        return bot_reply(reply_token, 'Your most recent order from {} was on {}: {} (${})'.format(restaurant, last_time.strftime("%m/%d"), items, price))
      else:
        return bot_reply(reply_token, 'No order found from {}'.format(restaurant))

    # find restaurants from keywords
    if restaurant == 'what':
      found_restaurants = [r[0] for r in from_keywords(option)]
      if len(found_restaurants) > 0:
        return bot_reply(reply_token, 'Some {} options for you: {}'.format(option, ', '.join(found_restaurants)))
      else:
        return bot_reply(reply_token, 'Sorry, no match found 😥')
    if option.lower() == 'want' or option == '想吃':
      new_restaurant(restaurant)
      return bot_reply(reply_token, '👌🏼{} has been added to your 想吃清單🤤'.format(restaurant))

  # support more than 3 tokens
  user_id = get_or_create_user(event.source.user_id)
  restaurant_id = get_or_create_restaurant(restaurant)
  order_date = option
  if option.lower() == 'today' or option == '今天':
    order_date = datetime.now()
  if token_count == 3:
    new_bento(user_id, restaurant_id, order_date)
  else: # with price and/or items
    items = None
    price = None
    if tokens[3].isdigit() or tokens[3][0] == '$':
      try:
        price = int(tokens[3])
      except:
        price = int(tokens[3][1:])
      if token_count > 4:
        items = ','.join(tokens[4:])
    else:
      items = ','.join(tokens[3:])
    new_bento(user_id, restaurant_id, order_date, price, items)
  return bot_reply(reply_token, '防疫便當完成登記🍱✅')


def get_usage():
  return """Usage as follows:
  * First token can be 'bento' or '便當'
  * New bento entry:
    bento [restaurant] [date] [price] [items]
  * Check order frequency:
    bento [restaurant]
  * Check last order:
    bento [restaurant] when
  * Add new restaurant to bucket list:
    bento [restaurant] want
  * Get restaurants from bucket list:
    bento what
  * Get restaurants from keyword:
    bento what [keyword]
  * Get total spent on all bentos:
    bento total
  """

def bot_reply(reply_token, response):
  line_bot_api.reply_message(reply_token, TextSendMessage(text=response))

def from_keywords(keyword):
  sql = """
    SELECT DISTINCT(r.name) FROM restaurants r
    JOIN bentos b ON b.restaurant_id = r.id
    WHERE b.items LIKE %s ESCAPE '';
  """
  return __get_all(sql, ('%{}%'.format(keyword),))

def check_last_order(restaurant):
  sql = """
    SELECT b.order_date, b.items, b.price 
    FROM bentos b JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.name = %s
    ORDER BY b.order_date DESC
    LIMIT 1;
  """
  return __get_all(sql, (restaurant,))

def check_frequency(restaurant):
  sql = """
    SELECT COUNT(*) FROM bentos b
    JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.name = %s;
  """
  return __get_first_row(sql, (restaurant,))

def get_bento_count():
  sql = """
    SELECT COUNT(*) FROM bentos b;
  """
  return __get_first_row(sql, ())

def get_or_create_restaurant(name):
  found_rest = find_restaurant(name)
  if found_rest:
    return found_rest
  else:
    new_restaurant(name)
    return find_restaurant(name)

def get_or_create_user(line_id):
  found_user = find_user(line_id)
  if found_user:
    return found_user
  else:
    new_user(line_id)
    return find_user(line_id)

def get_bucket_list():
  sql = """
    SELECT r.name FROM restaurants r
    LEFT JOIN bentos b on b.restaurant_id = r.id
    WHERE b.id isnull;
    """
  return __get_all(sql, ())

def find_restaurant(name):
  return __get_first_row("SELECT id FROM restaurants WHERE name = %s;", (name,))

def find_user(line_id):
  return __get_first_row("SELECT id FROM users WHERE line_id = %s;", (line_id,))

def new_user(line_id, name='Alice Chen'):
  __insert_or_update("""
    INSERT INTO users (line_id, name, created_at)
    VALUES (%s, %s, %s);
    """, (line_id, name, datetime.now()))

def new_bento(user_id, restaurant_id, order_date, price=None, items=None):
  last_order_sql = """
    SELECT b.id 
    FROM bentos b WHERE b.restaurant_id = %s AND date(b.order_date) = date(%s)
    LIMIT 1;
  """
  last_order = __get_first_row(last_order_sql, (restaurant_id, order_date))
  # update if record exists
  if last_order:
    __insert_or_update("UPDATE bentos SET items = %s, price = %s WHERE id = %s", (items, price, last_order))
  else:
    sql = """
      INSERT INTO bentos (user_id, restaurant_id, order_date, created_at, price, items) 
      VALUES (%s, %s, %s, %s, %s, %s);
    """
    __insert_or_update(sql, (user_id, restaurant_id, order_date, datetime.now(), price, items))

def new_restaurant(name):
  __insert_or_update("""
    INSERT INTO restaurants (name, created_at) 
    VALUES (%s, %s);
    """, (name, datetime.now()))

def __insert_or_update(sql, param):
  cur.execute(sql, param)
  conn.commit()

def __get_first_row(sql, param):
  cur.execute(sql, param)
  res = cur.fetchone()
  if res:
    return res[0]

def __get_all(sql, param):
  cur.execute(sql, param)
  return cur.fetchall()

if __name__ == '__main__':
  app.run()
