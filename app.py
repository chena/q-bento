from flask import Flask, abort

from linebot import (
  LineBotApi, WebhookHandler
)

from linebot.exceptions import (
  InvalidSignatureError
)

from linebot.models import (
  MessageEvent, TextMessage, TextSendMessage
)

app = Flask(__name__)

line_bot_api = LineBotApi('CHANNE_ACCESS_TOKEN')
handler = WebhookHandler('CHANNEL_SECRET')

@app.route('/callback', methods=['POST'])
def callback():
  # get X-Line-Signature header value
  signature = requset.headers['X-Line-Signature']

  # get request body as text
  body = request.get_date(as_text=True)
  app.logger.info('requset body', body)

  # handle webhook body
  try:
    handler.handle(body, signature)
  except InvalidSignatureError:
    print('Invalid signature. Please check your channel access token/secret.')
  return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
  line_bot_api.reply_message(
    event.reply_token,
    TextSendMessage(text=event.message.text))

if __name__ == '__main__':
  app.run()
