import csv
import logging

from typing import Any, Optional, Type, cast
from typing_extensions import Literal
from types import TracebackType
from pathlib import Path

import gevent

from gevent.pywsgi import WSGIServer

from flask import Flask, request, jsonify, Response as FlaskResponse

logger = logging.getLogger('webserver')


app = Flask('webserver')


@app.route('/api/v1/resources/dogs')
def app_get_dog_fact() -> FlaskResponse:
    _ = int(request.args.get('number', ''))

    return jsonify(['woof woof wooof'])


@app.route('/facts')
def app_get_cat_fact() -> FlaskResponse:
    _ = int(request.args.get('limit', ''))

    return jsonify(['meow meow meow'])


@app.route('/books/<book>.json')
def app_get_book(book: str) -> FlaskResponse:
    with open(f'{Path.cwd()}/features/requests/books/books.csv', 'r') as fd:
        reader = csv.DictReader(fd)
        for row in reader:
            if row['book'] == book:
                return jsonify({
                    'number_of_pages': row['pages'],
                    'isbn_10': [row['isbn_10']] * 2,
                    'authors': [
                        {'key': '/author/' + row['author'].replace(' ', '_').strip() + '|' + row['isbn_10'].strip()},
                    ]
                })


@app.route('/author/<author_key>.json')
def app_get_author(author_key: str) -> FlaskResponse:
    name, _ = author_key.rsplit('|', 1)

    return jsonify({
        'name': name.replace('_', ' ')
    })


@app.errorhandler(404)
def catch_all(_: Any) -> FlaskResponse:
    return jsonify({}, status=200)


class Webserver:
    _web_server: WSGIServer

    def __init__(self, port: int = 0) -> None:
        self._web_server = WSGIServer(
            ('0.0.0.0', port),
            app,
            log=None,
        )
        logger.debug(f'created webserver on port {port}')

    @property
    def port(self) -> int:
        return cast(int, self._web_server.server_port)

    def start(self) -> None:
        gevent.spawn(lambda: self._web_server.serve_forever())
        gevent.sleep(0.01)
        logger.debug(f'started webserver on port {self.port}')

    def __enter__(self) -> 'Webserver':
        self.start()

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Literal[True]:
        self._web_server.stop_accepting()
        self._web_server.stop()

        logger.debug(f'stopped webserver on port {self.port}')

        return True
