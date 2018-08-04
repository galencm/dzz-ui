import argparse
import atexit
import redis

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout

from ma_cli import data_models
from lings import ruling, pipeling

r_ip, r_port = data_models.service_connection()
binary_r = redis.StrictRedis(host=r_ip, port=r_port)
redis_conn = redis.StrictRedis(host=r_ip, port=r_port, decode_responses=True)

class DzzApp(App):

    def __init__(self, *args, **kwargs):
        # store kwargs to passthrough
        self.kwargs = kwargs
        if kwargs["db_host"] and kwargs["db_port"]:
            global binary_r
            global redis_conn
            db_settings = {"host" :  kwargs["db_host"], "port" : kwargs["db_port"]}
            binary_r = redis.StrictRedis(**db_settings)
            redis_conn = redis.StrictRedis(**db_settings, decode_responses=True)

        super(DzzApp, self).__init__()

    def save_session(self):
        pass

    def build(self):
        root = BoxLayout()
        return root

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-host",  help="db host ip, requires use of --db-port")
    parser.add_argument("--db-port", type=int, help="db port, requires use of --db-host")
    args = parser.parse_args()

    if bool(args.db_host) != bool(args.db_port):
        parser.error("--db-host and --db-port values are both required")

    app = DzzApp(**vars(args))
    atexit.register(app.save_session)
    app.run()