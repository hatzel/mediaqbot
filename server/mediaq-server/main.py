from telegram.ext import Updater, CommandHandler
import logging
from os import environ
from flask import Flask, jsonify, request, abort
from flask_redis import FlaskRedis
import uuid
import json
import names
from hashlib import sha256
from urllib.parse import urlparse

app = Flask(__name__)
redis_store = FlaskRedis(app)

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


logger = logging.getLogger(__name__)
if not environ.get("MEDIAQ_PEPPER"):
    logger.warn("No MEDIAQ_PEPPER provided, playlist ids will be guessable.")


def get_name(name, pepper=environ.get("MEDIAQ_PEPPER")):
    hashed = sha256((str(name) + str(pepper)).encode("utf-8")).digest()
    return names.get_name(
        int.from_bytes(hashed, byteorder='big', signed=False)
    )


def start(bot, update):
    update.message.reply_text(
        "The queue id for this chat is: %s" % get_name(update.message.chat_id)
    )


def help(bot, update):
    update.message.reply_text("""Welcome to MediaQBot!
Use /add to add a URL of a web video.

When starting the player, this will be your playlist id:
%s""" % get_name(update.message.chat_id))


def valid_url(url):
    parsed = urlparse(url)
    return len(parsed.scheme) > 0 and len(parsed.netloc) > 0


def add(bot, update, args):
    chat_id = get_name(update.message.chat_id)
    url = args[0] if len(args) > 0 else None
    if url and valid_url(url):
        tup = json.dumps({"id": str(uuid.uuid4()), "url": url})
        redis_store.rpush(chat_id, tup)
        logger.info("enqing URL %s for chat [%s]" % (url, chat_id))
    elif url:
        update.message.reply_text("""Sorry, that doesn't look like a valid URL
For examples see /help.""")
    else:
        update.message.reply_text("""Please provide a URL!
For examples see /help.""")


def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))


def decode_videos_entry(videos, single=False):
    lst = [json.loads(v.decode("utf-8")) for v in videos]
    if single:
        try:
            return lst[0]
        except IndexError:
            return {}
    else:
        return lst


@app.route("/<chat_id>/current")
def current_video(chat_id):
    return jsonify(
        decode_videos_entry(redis_store.lrange(chat_id, 0, 1), single=True)
    )


@app.route("/<chat_id>/next")
def next_video(chat_id):
    return jsonify(
        decode_videos_entry(redis_store.lrange(chat_id, 1, 2), single=True)
    )


@app.route("/<chat_id>")
def video_list(chat_id):
    videos = decode_videos_entry(redis_store.lrange(chat_id, 0, 10))
    return jsonify(videos)


@app.route("/<chat_id>/pop", methods=["POST"])
def pop_video(chat_id):
    first = redis_store.lindex(chat_id, 0)
    if first is None:
        abort(404)
    q = redis_store.lrange(chat_id, 0, 100)
    for i in q:
        decoded = json.loads(i.decode("utf-8"))
        if request.get_json()["id"] == decoded["id"]:
            return jsonify(
                {"popped": json.loads(redis_store.lpop(chat_id).decode("utf-8"))}
            )
    abort(400)



def main(debug=False):
    updater = Updater(environ.get("TELEGRAM_TOKEN"))
    if debug:
        redis_store.flushdb()

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("add", add, pass_args=True))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("start", start))

    dp.add_error_handler(error)

    updater.start_polling()
    if debug:
        app.run()


if __name__ == "__main__":
    debug = environ.get("MEDIAQ_DEBUG", False)
    main(debug=debug)
