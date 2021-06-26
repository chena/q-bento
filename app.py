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

  if (tokens[0].startswith('bento') and len(tokens) > 2):
    restaurant, date = tokens[1:]
    user_id = get_or_create_user(event.source.user_id)
    restaurant_id = get_or_create_restaurant(restaurant)
    new_bento(user_id, restaurant_id, date)
  line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))

def get_or_create_restaurant(name):
  found_rest = find_restaurant(name)
  if found_rest:
    return found_rest
  else:
    return new_restaurant(name)

def get_or_create_user(line_id):
  found_user = find_user(line_id)
  if found_user:
    return found_user
  else:
    return new_user(line_id)

def find_restaurant(name):
  cur = conn.cursor()
  cur.execute("SELECT id FROM restaurants WHERE name = %s;", (name,))
  res = cur.fetchone()
  cur.close()
  if res:
    return res[0]

def find_user(line_id):
  cur = conn.cursor()
  cur.execute("SELECT id FROM users WHERE line_id = %s;", (line_id,))
  res = cur.fetchone()
  cur.close()
  if res:
    return res[0]

def new_user(line_id, name='Alice Chen'):
  cur = conn.cursor()
  # new user entry
  cur.execute("INSERT INTO users (line_id, name, created_at) VALUES (%s, %s, %s);", (line_id, name, datetime.now()))
  conn.commit()
  cur.close()

def new_bento(user_id, restaurant_id, order_date):
  cur = conn.cursor()
  # new bento entry
  cur.execute("INSERT INTO bentos (user_id, restaurant_id, order_date, created_at) VALUES (%s, %s, %s, %s);", (user_id, restaurant_id, order_date, datetime.now()))
  conn.commit()
  cur.close()

def new_restaurant(name):
  cur = conn.cursor()
  # new bento entry
  cur.execute("INSERT INTO restaurant (name, created_at) VALUES (%s, %s);", (name, datetime.now()))
  conn.commit()
  cur.close()

if __name__ == '__main__':
  app.run()
