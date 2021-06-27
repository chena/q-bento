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
  response = message
  tokens = message.split()
  token_count = len(tokens)

  if (tokens[0].startswith('bento')):
    if token_count == 1:
      response = 'Usage: "bento [restaurant] [date] [items]"'
    if token_count == 2:
      restaurant = tokens[1]
      freq = check_frequency(restaurant)
      response = 'You ate at {} {} times during quarantine!'.format(restaurant, freq)
    elif token_count > 4:
      response = 'Invalid: please follow format "bento [restaurant] [date] [items]"'
    else:
      restaurant, date = tokens[1:3]
      user_id = get_or_create_user(event.source.user_id)
      restaurant_id = get_or_create_restaurant(restaurant)
      if token_count == 3:
        new_bento(user_id, restaurant_id, date)
      else: # with options
        items = tokens[3]
        new_bento(user_id, restaurant_id, date, items)
  line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))

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
  cur = conn.cursor()
  cur.execute(sql, param)
  conn.commit()
  cur.close()

def __get_first_row(sql, param):
  cur = conn.cursor()
  cur.execute(sql, param)
  res = None
  try:
    res = cur.fetchone()
    if res:
      res = res[0]
  finally:
    cur.close()
    return res

if __name__ == '__main__':
  app.run()
