# scheduler-playground

Just playing around a bit with python and `APScheduler` to implement `cron` like behaviour. The _jobs_ are pulled from the JSON File `config.json`, a `Watcher/Observer` keeps the crontabs update, as you change
in the file. Pydantic is a left-over that I used to create a REST API like interface to update the jobs in the json file via FASTapi.

At the moment the jobs executing and some further details need still to be implemented.