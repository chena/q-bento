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
  if token_count > 4:
    return bot_reply(reply_token, get_usage())
  
  if token_count == 2:
    restaurant = tokens[1]
    if restaurant == 'what':
      bucket_list = [r[0] for r in get_bucket_list()]
      return bot_reply(reply_token, 'Some options for you: {}'.format(', '.join(bucket_list)))
    freq = check_frequency(restaurant)
    return bot_reply(reply_token, 'You ordered from {} {} times during quarantine!'.format(restaurant, freq))
  
  restaurant, option = tokens[1:3]
  # check last order date
  if option.lower() == 'when':
    last_time = last_order_date(restaurant).strftime("%m/%d")
    return bot_reply(reply_token, 'Your most recent order from {} is on {}.'.format(restaurant, last_time))
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

  user_id = get_or_create_user(event.source.user_id)
  restaurant_id = get_or_create_restaurant(restaurant)
  if option.lower() == 'today' or option == '今天':
    option = datetime.now()
  if token_count == 3:
    new_bento(user_id, restaurant_id, option)
  else: # with items
    items = tokens[3]
    new_bento(user_id, restaurant_id, option, items)
  return bot_reply(reply_token, '防疫便當完成登記🍱✅')


def get_usage():
  return """Usage as follows:
  * First token can be 'bento' or '便當'
  * New bento entry:
    bento [restaurant] [date] [items]
  * Check order frequency:
    bento [restaurant]
  * Check last order date:
    bento [restaurant] when
  * Add new restaurant to bucket list:
    bento [restaurant] want
  * Get restaurants from bucket list:
    bento what
  * Get restaurants from keyword:
    bento what [keyword]
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

def last_order_date(restaurant):
  sql = """
    SELECT b.order_date 
    FROM bentos b JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.name = %s
    ORDER BY b.order_date DESC
    LIMIT 1;
  """
  return __get_first_row(sql, (restaurant,))

def check_frequency(restaurant):
  sql = """
    SELECT COUNT(*) FROM bentos b
    JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.name = %s;
  """
  return __get_first_row(sql, (restaurant,))

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
  __insert("""
    INSERT INTO users (line_id, name, created_at)
    VALUES (%s, %s, %s);
    """, (line_id, name, datetime.now()))

def new_bento(user_id, restaurant_id, order_date, items=None):
  __insert("""
    INSERT INTO bentos (user_id, restaurant_id, order_date, created_at, items) 
    VALUES (%s, %s, %s, %s, %s);
    """, (user_id, restaurant_id, order_date, datetime.now(), items))

def new_restaurant(name):
  __insert("""
    INSERT INTO restaurants (name, created_at) 
    VALUES (%s, %s);
    """, (name, datetime.now()))

def __insert(sql, param):
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
