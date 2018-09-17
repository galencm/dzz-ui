# dzz-ui

_dss-ui v2_

## Installation

Pip:

```
pip3 install git+https://github.com/galencm/dzz-ui --user --process-dependency-links
```

Develop while using pip:

```
git clone https://github.com/galencm/dzz-ui
cd dzz-ui/
pip3 install --editable ./ --user --process-dependency-links
```

Setup linting and formatting git commit hooks:

```
cd dzz-ui/
pre-commit install
pre-commit install -t commit-msg
```

## Usage

```
dzz-ui --size=1500x800 -- --db-key glworb:55ff205b-ae84-407c-9c2c-ca47ef98e57d --db-key-field binary_key --db-host 127.0.0.1 --db-port 6379 
```

**A redis server must be accessible.** 

To start one locally:

* Create a config file to enable keyspace events and snapshot.
* Run a redis-server process in the background

```
printf "notify-keyspace-events KEA\nSAVE 60 1\n" >> redis.conf
redis-server redis.conf --port 6379 &
```

The server can be stopped with the command:
```
redis-cli -p 6379 shutdown
```

## Contributing

[Contribution guidelines](CONTRIBUTING.md)

## License
Mozilla Public License, v. 2.0

[http://mozilla.org/MPL/2.0/](http://mozilla.org/MPL/2.0/)

