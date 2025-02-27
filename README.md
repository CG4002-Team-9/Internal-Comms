# Internal-Comms
* The relay servers for gloves, vests, and legs beetles are in the `relay_to_external` directory.
* The initial setup for beetles can be found in the final report's appendix.

## Setup
Install libglib2.0-dev, required for bluepy library.

```
sudo apt-get install python-pip libglib2.0-dev
```

Install the requirements.txt
```
pip install -r requirements.txt
```
or
```
python -m pip install -r requirements.txt
```

Install pm2
```
sudo apt install npm
sudo npm install pm2 -g
```
Add the .env file to the directory

## Run
This runs all beetles server for 2 players.
```
pm2 start ecosystem.config.js
```

To restart, need to delete first, then run again
```
pm2 delete ecosystem.config.js
```

To view the logs
```
pm2 logs
```
