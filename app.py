import os
import io
from datetime import datetime
from flask import Flask, request, send_file
import psycopg2
import phonenumbers
import random
import requests
import time
from flask_apscheduler import APScheduler

from linebot import (
  LineBotApi, WebhookHandler
)

from linebot.exceptions import (
  InvalidSignatureError
)

from linebot.models import (
  MessageEvent, TextMessage, TextSendMessage, ImageMessage, ImageSendMessage, 
  CarouselColumn, CarouselTemplate, TemplateSendMessage, URIAction,
  QuickReply, QuickReplyButton, MessageAction
)

DATABASE_URL = os.environ['DATABASE_URL'] 
APP_URL = os.environ['APP_URL']
TOKEN = os.environ['CHANNE_ACCESS_TOKEN']
LINE_GROUP_ID = os.environ['LINE_GROUP_ID']
CHANNEL_SECRET = os.environ['CHANNEL_SECRET']

DATE_FORMAT = '%Y-%m-%d'

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

app = Flask(__name__)

line_bot_api = LineBotApi(TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
headers = {
  "Content-Type": "application/json",
  "Authorization": "Bearer " + TOKEN
}

# initialize scheduler
scheduler = APScheduler()
scheduler.api_enabled = True
scheduler.init_app(app)
scheduler.start()

@scheduler.task('cron', id='lunch_push', day_of_week='*', hour='4', minute='30')
def lunch_push():
  last_bento_date = get_last_bento()[1]
  if datetime.now().strftime(DATE_FORMAT) != str(last_bento_date):
    line_bot_api.push_message(LINE_GROUP_ID, TextSendMessage(text='午安😎今天吃了什麼呢？'))
  else:
    print('BENTO reported!')

@scheduler.task('cron', id='morning_push', day_of_week='*', hour='3', minute='0')
def morning_push():
  line_bot_api.push_message(LINE_GROUP_ID, TextSendMessage(
    text='早安☀️今天吃什麼呢？', quick_reply=QuickReply(items=[
      QuickReplyButton(action=MessageAction(label="Q便當隨機選🤖", text="bento pick")),
      QuickReplyButton(action=MessageAction(label="看看想吃清單❤️", text="bento what")),
      QuickReplyButton(action=MessageAction(label="來吃久違的便當🍱", text="bento old"))
    ])
  ))

@scheduler.task('cron', id='test_push', hour='7', minute='12')
def test_push():
  line_bot_api.push_message(os.environ['LINE_USER_ID'], TextSendMessage(text='TEST TEST'))

# scheduler.add_job(test_push, 'cron', hour='8', minute='3')

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

@app.route('/images/<bento_id>', methods=['POST', 'GET'])
def get_or_save_image(bento_id):
  if request.method == 'POST':
    body = request.get_json(force=True)
    binary_data = requests.get(body['url'], stream=True).content
    __insert_or_update('UPDATE bentos SET image = %s WHERE id = %s', (binary_data, bento_id))
    return 'OK'
  if bento_id == 'last':
    bento_id = get_last_bento()[0]
  image_binary = get_bento_image(bento_id)
  return send_file(
    io.BytesIO(image_binary),
    mimetype='image/jpeg',
    as_attachment=False)

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
  message = event.message
  reply_token = event.reply_token
  image_url = 'https://api-data.line.me/v2/bot/message/{}/content'.format(message.id)
  r = requests.get('https://api-data.line.me/v2/bot/message/{}/content'.format(message.id), headers=headers)
  content = r.text
  # persist binary data
  bento_id = get_last_bento('created_at')[0]
  __insert_or_update('UPDATE bentos SET image = %s WHERE id = %s', (r.content, bento_id))
  return bot_reply(reply_token, 'Bento image uploaded! 📸')

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
  message = event.message.text
  reply_token = event.reply_token
  response = message
  tokens = message.split()
  token_count = len(tokens)
  first_token = tokens[0].lower()
  source = event.source
  room_id = source.room_id if source.type == 'room' else None
  user_id = get_or_create_user(source.user_id)

  if not (first_token.startswith('bento') or first_token.startswith('便當')):
    # detect URL shared from google map with restaurant name info
    if 'https://maps' in response and not tokens[0].startswith('https'):
      lines = message.split('\n')
      restaurant = lines[0]
      phone = None
      url = None
      # check if second line is a phone number or a link
      p = phonenumbers.parse(lines[1], 'TW')
      if phonenumbers.is_valid_number(p):
        phone, url = lines[1:]
      else:
        url = lines[1]
      r = new_restaurant(restaurant, url, phone)
      if r:
        return bot_reply(reply_token, 'Thanks for sharing, {} info updated'.format(restaurant))
      return bot_reply(reply_token, 'Thanks for sharing, {} added to your bucket list 😋'.format(restaurant))
    return bot_reply(reply_token, response)
    
  if token_count == 1:
    return bot_reply(reply_token, get_usage())
  if token_count == 2:
    second_token = tokens[1]
    if second_token == 'what':
      bucket_list = [r[0] for r in get_bucket_list()]
      return bot_reply(reply_token, 'Some options for you: {}'.format(', '.join(bucket_list)))
    elif second_token == 'pick' or second_token == '選':
      name, phone, link, tabetai = pick_restaurant()
      reply = '🍱 {}'.format(name)
      if phone:
        reply += '\n☎️ {}'.format(phone)
      if link:
        reply += '\n🔗 {}'.format(link)
      if tabetai:
        reply += '\n👍 {}'.format(tabetai)
      return bot_reply(reply_token, reply)
    elif second_token == 'old':
      old_bentos = [r[0] for r in get_old_bentos()]
      return bot_reply(reply_token, 'Some options for you: {}'.format(', '.join(old_bentos)))
    elif second_token == 'total' or second_token == '合計':
      total = __get_first_row('SELECT SUM(price) FROM bentos;', ())
      bento_count = get_bento_count()
      avg = round(total/bento_count)
      return bot_reply(reply_token, 'You have spent ${} in total on {} 🍱 during quarantine! (${} per day on average)🤑'.format(total, bento_count, avg)) 
    else: # check history
      bentos = get_bentos(second_token)
      freq = len(bentos)
      total = sum([r[1] for r in bentos])
      bento_cards = list(filter(None, [b if b[2] else None for b in bentos]))
      reply_msg = 'You ordered from {} {} time{} during quarantine! (total ${})'.format(second_token, freq, ('s' if freq > 1 else ''), total)
      messages = [TextSendMessage(text=reply_msg)]
      if len(bento_cards):
        columns = map(lambda b: CarouselColumn(
          thumbnail_image_url='{}images/{}'.format(APP_URL, b[0]),
          title=b[3].strftime("%m/%d"),
          text='{} (${})'.format('' if not b[4] else b[4], b[1]),
          actions=[
            URIAction(label='放大', uri='{}images/{}'.format(APP_URL, b[0])), 
            URIAction(label='Order Again', uri=b[5]) if b[5] else None
        ]), bento_cards)
        image_messages = TemplateSendMessage(
          alt_text='bento',
          template=CarouselTemplate(columns=list(columns))
        )
        messages.append(image_messages)
      return line_bot_api.reply_message(reply_token, messages)

  restaurant, option = tokens[1:3]
  if token_count == 3:
  # check last order date
    if option.lower() == 'when':
      last_order = check_last_order(restaurant)
      if last_order:
        last_time, items, price, bento_id, bento_image = last_order[0]
        reply_msg = 'Your most recent order from {} was on {}: {} (${})'.format(restaurant, last_time.strftime("%m/%d"), items, price)
        if not bento_image:
          return bot_reply(reply_token, reply_msg)
        image_url = '{}images/{}'.format(APP_URL, bento_id)
        return line_bot_api.reply_message(reply_token, [
          TextSendMessage(text=reply_msg),
          ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
        ])
      else:
        return bot_reply(reply_token, 'No order found from {}'.format(restaurant))

    if restaurant == 'what':
      # check if third token is a date
      try:
        if option in ['today', '今天']:
          order_date = datetime.today().strftime(DATE_FORMAT)
        elif option == ['yesterday', '昨天']:
          order_date = datetime.today().strftime(DATE_FORMAT) - datetime.timedelta(days=1)
        else:
          order_date = datetime.strptime(option, DATE_FORMAT)
        bentos = get_bento_from_date(order_date)
        formatted_date = order_date.strftime("%m/%d")
        if not len(bentos):
          return bot_reply(reply_token, 'No order from {}'.format(formatted_date))
        restaurants = [b[3] for b in bentos]
        reply_msg = 'You ordered from {} on {}'.format(' and '.join(restaurants), formatted_date)
        bento_cards = list(filter(None, [b if b[2] else None for b in bentos]))
        messages = [TextSendMessage(text=reply_msg)]
        if len(bento_cards):
          columns = map(lambda b: CarouselColumn(
            thumbnail_image_url='{}images/{}'.format(APP_URL, b[0]),
            title=b[3],
            text='{} (${})'.format('' if not b[4] else b[4], b[1]),
            actions=[
              URIAction(label='放大', uri='{}images/{}'.format(APP_URL, b[0])), 
              URIAction(label='Order Again', uri=b[5]) if b[5] else None
          ]), bento_cards)
          image_messages = TemplateSendMessage(
            alt_text='bento',
            template=CarouselTemplate(columns=list(columns))
          )
          messages.append(image_messages)
          return line_bot_api.reply_message(reply_token, messages)
      except ValueError as e:
        print('ERROR', e)
        # find restaurants from keywords
        found_restaurants = [r[0] for r in from_keywords(option)]
        if len(found_restaurants) > 0:
          return bot_reply(reply_token, 'Some {} options for you: {}'.format(option, ', '.join(found_restaurants)))
        else:
          return bot_reply(reply_token, 'Sorry, no match found 😥')
    # add restaurant to list
    if option.lower() == 'want' or option == '想吃':
      new_restaurant(restaurant)
      return bot_reply(reply_token, '👌🏼{} has been added to your 想吃清單🤤'.format(restaurant))
    # add image to bento
    if option.startswith('https:'):
      binary_data = requests.get(option, stream=True).content
      if binary_data:
        last_order = check_last_order(restaurant)
        bento_id = last_order[0][3]
        __insert_or_update('UPDATE bentos SET image = %s WHERE id = %s', (binary_data, bento_id))
        return bot_reply(reply_token, 'Bento image from {} uploaded! 📸'.format(restaurant))

  # support more than 3 tokens
  restaurant_id = get_or_create_restaurant(restaurant)
  order_date = option
  if option.lower() == 'today' or option == '今天':
    order_date = datetime.now()
  if token_count == 3:
    new_bento(user_id, restaurant_id, order_date, room_id)
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
    new_bento(user_id, restaurant_id, order_date, price, items, room_id)
  return bot_reply(reply_token, '防疫便當完成登記🍱✅')


def get_usage():
  return """Usage as follows:
  * First token can be 'bento' or '便當'
  * New bento entry:
    bento [restaurant] [date] [price] [items]
  * Check order history from a restaurant:
    bento [restaurant]
  * Check last order from a restrant:
    bento [restaurant] when
  * Check order from a date:
    bento what [date]
  * Add new restaurant to bucket list:
    bento [restaurant] want
  * Get restaurants from bucket list:
    bento what
  * Get restaurants from keyword:
    bento what [keyword]
  * Get total spent on all bentos:
    bento total
  * Pick one restaurant from bucket list:
    bento pick
  """

def bot_reply(reply_token, response):
  line_bot_api.reply_message(reply_token, TextSendMessage(text=response))

def pick_restaurant():
  restaurants = get_bucket_list()
  index = random.randint(0, len(restaurants)-1)
  return restaurants[index]

def from_keywords(keyword):
  sql = """
    SELECT DISTINCT(r.name) FROM restaurants r
    JOIN bentos b ON b.restaurant_id = r.id
    WHERE r.name LIKE %s ESCAPE '' OR b.items LIKE %s ESCAPE '' OR r.tabetai LIKE %s ESCAPE '';
  """
  keyword = '%{}%'.format(keyword)
  return __get_all(sql, (keyword, keyword, keyword))

def check_last_order(restaurant):
  name = '%{}%'.format(restaurant)
  sql = """
    SELECT b.order_date, b.items, b.price, b.id, b.image
    FROM bentos b JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.name LIKE %s ESCAPE ''
    ORDER BY b.order_date DESC
    LIMIT 1;
  """
  return __get_all(sql, (name,))

def get_bento_from_date(order_date):
  sql = """
    SELECT b.id, b.price, b.image, r.name, b.items, r.url
    FROM bentos b JOIN restaurants r ON b.restaurant_id = r.id
    WHERE date(b.order_date) = %s;
  """
  return __get_all(sql, (order_date,))

def get_bentos(restaurant, room_id=None):
  name = '%{}%'.format(restaurant)
  sql = """
    SELECT b.id, b.price, b.image, b.order_date, b.items, r.url 
    FROM bentos b JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.name LIKE %s ESCAPE ''
    ORDER BY order_date DESC;
  """
  return __get_all(sql, (name,))

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
    SELECT r.name, r.phone, r.url, r.tabetai FROM restaurants r
    LEFT JOIN bentos b on b.restaurant_id = r.id
    WHERE r.available is not false AND b.id isnull;
    """
  return __get_all(sql, ())

def find_restaurant(name):
  fuzzy_name = '%{}%'.format(name)
  return __get_first_row("SELECT id FROM restaurants WHERE name LIKE %s ESCAPE '';", (fuzzy_name,))

def find_user(line_id):
  return __get_first_row("SELECT id FROM users WHERE line_id = %s;", (line_id,))

def get_last_bento(order_by='order_date'):
  last_order_sql = """
    SELECT b.id, date(b.order_date)
    FROM bentos b 
    ORDER BY {} DESC
    LIMIT 1;
  """.format(order_by)
  return __get_all(last_order_sql, ())[0]

def get_bento_image(bento_id):
  return __get_first_row("""
    SELECT image FROM bentos WHERE id = %s
  """, (str(bento_id),))

def get_old_bentos():
  sql = """
    SELECT r.name , MAX(b.order_date) AS odate
    FROM bentos b JOIN restaurants r ON b.restaurant_id = r.id
    WHERE r.dame IS NOT true AND r.available IS NOT false
    GROUP BY r.name ORDER BY odate
    LIMIT 3;
  """
  return __get_all(sql, ())

def new_user(line_id, name=None):
  __insert_or_update("""
    INSERT INTO users (line_id, name, created_at)
    VALUES (%s, %s, %s);
    """, (line_id, name, datetime.now()))

def new_bento(user_id, restaurant_id, order_date, price=None, items=None, room_id=None):
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
      INSERT INTO bentos (user_id, restaurant_id, order_date, created_at, price, items, room_id) 
      VALUES (%s, %s, %s, %s, %s, %s, %s);
    """
    __insert_or_update(sql, (user_id, restaurant_id, order_date, datetime.now(), price, items, room_id))

def new_restaurant(name, url=None, phone=None):
  r = find_restaurant(name)
  if r:
    __insert_or_update("""
    UPDATE restaurants SET url = %s, phone = %s WHERE name = %s
    """, (url, phone, name))
    return True
  else:
    __insert_or_update("""
      INSERT INTO restaurants (name, url, phone, created_at) 
      VALUES (%s, %s, %s, %s);
      """, (name, url, phone, datetime.now()))
    return False

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
  app.run(use_reloader=False)
