from flask import Flask
from flask import request
from threading import Thread
import time
import requests


app = Flask('')

@app.route('/')
def home():
  return "I'm alive"

def run():
  app.run(host='0.0.0.0', port=5000)

def keep_alive():
    if os.environ.get("RENDER"):  # будет работать только на Render
        t = threading.Thread(target=run)
        t.start()

