# -*- coding: utf-8 -*-
import sys
sys.path.append('./libs')
import logging
import requests
import psycopg2
import fb_bot
import json
import base64
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

client_id = ""
client_secret = ""

PAGE_TOKEN = ""
VERIFY_TOKEN = ""

host = ""
port = 5432
username = ""
database = "postgres"
password = ""

try:
    conn = psycopg2.connect(
    host=host,
    database=database,
    user=username,
    password=password)
    cursor = conn.cursor()
except:
    logging.error("could not connect to rds")
    sys.exit(1)

bot = fb_bot.Bot(PAGE_TOKEN)


def lambda_handler(event, context):

    # event['params'] only exists for HTTPS GET

    if 'params' in event.keys():

        if event['params']['querystring']['hub.verify_token'] == VERIFY_TOKEN:
            return int(event['params']['querystring']['hub.challenge'])
        else:
            logging.error('wrong validation token')
            raise SystemExit
    else:
        messaging = event['entry'][0]['messaging'][0]
        user_id = messaging['sender']['id']

        logger.info(messaging)
        artist_name = messaging['message']['text']

        query = "SELECT image_url, url FROM artists WHERE name = '{}'".format(artist_name)
        try:
            cursor.execute(query)
            raw = cursor.fetchall()
            if len(raw) == 0:
                sys.exit(0)
        except:
            text = search_artist(cursor, artist_name)
            bot.send_text(user_id, text)
            sys.exit(0)

        image_url, url = raw[0]

        payload = {
            'template_type': 'generic',
            'elements': [
                {
                    'title': "입력한 가수: '{}'".format(artist_name),
                    'image_url': image_url,
                    'subtitle': 'information',
                    'default_action': {
                        'type': 'web_url',
                        'url': url,
                        'webview_height_ratio': 'full'
                    }
                }
            ]
        }

        bot.send_attachment(user_id, "template", payload)
        # 새로 추가

        query4 = "SELECT id url FROM artists WHERE name = '{}'".format(artist_name)

        cursor.execute(query4)
        raw4 = cursor.fetchall()
        id, = raw4[0]

        query2 = "SELECT y_artist FROM related_artists ra WHERE artist_id = '{}'".format(id)

        cursor.execute(query2)
        raw2 = cursor.fetchall()
        yid, = raw2[0]

        query3 = "SELECT name, image_url, url FROM artists WHERE id = '{}'".format(yid)

        cursor.execute(query3)
        raw3 = cursor.fetchall()
        name, image_url2, url2 = raw3[0]

        payload2 = {
            'template_type': 'generic',
            'elements': [
                {
                    'title': "유사한 가수: '{}'".format(name),
                    'image_url': image_url2,
                    'subtitle': 'information',
                    'default_action': {
                        'type': 'web_url',
                        'url': url2,
                        'webview_height_ratio': 'full'
                    }
                }
            ]
        }

        bot.send_attachment(user_id, "template", payload2)

        query = "SELECT t2.genre FROM artists t1 JOIN artist_genre t2 ON t2.artist_id = t1.id WHERE t1.name = '{}'".format(artist_name)

        cursor.execute(query)
        genres = []
        for (genre, ) in cursor.fetchall():
            genres.append(genre)

        text = "{}의 장르는?".format(artist_name)
        bot.send_text(user_id, text)
        bot.send_text(user_id, ', '.join(genres))


        ## 만약에 아티스트가 없을시에는 아티스트 추가

        ## Spotify API hit --> Artist Search
        ## Database Upload
        ## One second
        ## 오타 및 아티스트가 아닐 경우


def get_headers(client_id, client_secret):

    endpoint = "https://accounts.spotify.com/api/token"
    encoded = base64.b64encode("{}:{}".format(client_id, client_secret).encode('utf-8')).decode('ascii')

    headers = {
        "Authorization": "Basic {}".format(encoded)
    }

    payload = {
        "grant_type": "client_credentials"
    }

    r = requests.post(endpoint, data=payload, headers=headers)

    access_token = json.loads(r.text)['access_token']

    headers = {
        "Authorization": "Bearer {}".format(access_token)
    }

    return headers


def insert_row(cursor, data, table):
    
    placeholders = ', '.join(['%s'] * len(data))
    columns = ', '.join(data.keys())
    key_placeholders = ', '.join(['{0}=%s'.format(k) for k in data.keys()])
    sql = "INSERT INTO %s ( %s ) VALUES ( %s ) ON CONFLICT ( %s ) DO UPDATE SET  %s" % (table, columns, placeholders, list(data.keys())[0] ,key_placeholders)
    cursor.execute("ROLLBACK")
    conn.commit()
    cursor.execute(sql, list(data.values())*2)

def invoke_lambda(fxn_name, payload, invocation_type='Event'):

    lambda_client = boto3.client('lambda')

    invoke_response = lambda_client.invoke(
        FunctionName = fxn_name,
        InvocationType = invocation_type,
        Payload = json.dumps(payload)
    )

    if invoke_response['StatusCode'] not in [200, 202, 204]:
        logging.error("ERROR: Invoking lmabda function: '{0}' failed".format(fxn_name))


    return invoke_response


def search_artist(cursor, artist_name):

    headers = get_headers(client_id, client_secret)

    ## Spotify Search API
    params = {
        "q": artist_name,
        "type": "artist",
        "limit": "1"
    }

    r = requests.get("https://api.spotify.com/v1/search", params=params, headers=headers)

    raw = json.loads(r.text)

    if raw['artists']['items'] == []:
        return "Could not find artist. Please Try Again!"

    artist = {}
    artist_raw = raw['artists']['items'][0]
    if artist_raw['name'] == artist_name:

        artist.update(
            {
                'id': artist_raw['id'],
                'name': artist_raw['name'],
                'followers': artist_raw['followers']['total'],
                'popularity': artist_raw['popularity'],
                'url': artist_raw['external_urls']['spotify'],
                'image_url': artist_raw['images'][0]['url']
            }
        )
        insert_row(cursor, artist, 'artists')
        conn.commit()
        for i in artist_raw['genres']:
            if len(artist_raw['genres']) != 0:
                insert_row(cursor, {'artist_id': artist_raw['id'], 'genre': i}, 'artist_genre')

        
        conn.commit()
        

        r = invoke_lambda('top-tracks', payload={'artist_id': artist_raw['id']})
        print(r)
        return "We added artist. Please try again in a second!"

        

    return "Could not find artist. Please Try Again!"
