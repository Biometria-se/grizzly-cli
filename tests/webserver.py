from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import gevent
from flask import Flask, jsonify, request
from flask import Response as FlaskResponse
from gevent.pywsgi import WSGIServer
from typing_extensions import Literal, Self

if TYPE_CHECKING:
    from types import TracebackType

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
    books = Path.joinpath(Path.cwd(), 'features', 'requests', 'books', 'books.csv')
    with books.open('r') as fd:
        reader = csv.DictReader(fd)
        for row in reader:
            if row['book'] == book:
                return jsonify({
                    'number_of_pages': row['pages'],
                    'isbn_10': [row['isbn_10']] * 2,
                    'authors': [
                        {'key': '/author/' + row['author'].replace(' ', '_').strip() + '|' + row['isbn_10'].strip()},
                    ],
                })

    response = jsonify({'success': False})
    response.status_code = 500

    return response


@app.route('/author/<author_key>.json')
def app_get_author(author_key: str) -> FlaskResponse:
    name, _ = author_key.rsplit('|', 1)

    return jsonify({
        'name': name.replace('_', ' '),
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
        logger.debug('created webserver on port %d', port)

    @property
    def port(self) -> int:
        port = self._web_server.server_port
        assert port is not None

        return port  # type: ignore[no-any-return]

    def start(self) -> None:
        gevent.spawn(lambda: self._web_server.serve_forever())
        gevent.sleep(0.01)
        logger.debug('started webserver on port %d', self.port)

    def __enter__(self) -> Self:
        self.start()

        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Literal[True]:
        self._web_server.stop_accepting()
        self._web_server.stop()

        logger.debug('stopped webserver on port %d', self.port)

        return True
