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
    user_line_id = event.source.user_id
    print(user_line_id)
    print(new_user(user_line_id))
    print(new_bento(find_user(user_line_id), find_restaurant(name), date))
  line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))

def find_restaurant(name):
  cur = conn.cursor()
  cur.execute("SELECT id FROM restauratns WHERE name = %s;", (name))
  id = cur.fetchone()[0]
  cur.close()
  return id

def find_user(line_id):
  cur = conn.cursor()
  cur.execute("SELECT id FROM users WHERE line_id = %s;", (line_id))
  id = cur.fetchone()[0]
  cur.close()
  return id

def new_user(line_id, name='Alice Chen'):
  cur = conn.cursor()
  # new user entry
  val = cur.execute("INSERT INTO users (line_id, name, created_at) VALUES (%s, %s, %s);", (line_id, name, datetime.now()))
  cur.close()
  return val

def new_bento(user_id, restaurant_id, order_date):
  cur = conn.cursor()
  # new bento entry
  val = cur.execute("INSERT INTO bentos (user_id, restaurant_id, order_date) VALUES (%s, %s, %s);", (user_id, restaurant_id, order_date))
  cur.close()
  return val

if __name__ == '__main__':
  app.run()
