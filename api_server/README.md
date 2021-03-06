# Chat With Anyone API Server

## Setup without docker (Ubuntu)

Create a virtual environment and install the requirements:

```bash
cd api_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt  # (venv) is supposed here and below
```

Install and run PostgreSQL:

```bash
sudo apt-get install postgresql-10
sudo service postgresql start
```

By default, the `postgres` user has no password. Let's set it:

```bash
sudo -U postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
```

Run the PostgreSQL interactive shell:

```bash
psql -U postgres -h localhost
```

Create the database and the user, then quit from the shell:

```sql
CREATE DATABASE chat_with_anyone;
CREATE USER chat_with_anyone WITH PASSWORD 'chat_with_anyone';
GRANT ALL PRIVILEGES ON DATABASE chat_with_anyone to chat_with_anyone;
\q
```

Apply the migrations to fill the database with the needed tables:

```bash
alembic upgrade head
```

## Setup with docker

1. Install `docker` and `docker-compose`
1. Build backend container via `docker-compose build`
1. Run database container via `docker-compose up -d chat-database`
1. Apply migrations via `docker-compose run --rm chat-backend alembic upgrade head`

## Start application without docker

Now run the freaking server!

```bash
python main.py
```

Or use the `aiohttp-devtools` CLI to get such features as live reload
and rich debug information for incoming requests into your console:

```bash
adev runserver .
```

Now go to `/api/docs` in your browser and get the Swagger UI to
explore this API.

## Start application with docker

```bash
docker-compose up
```

## Create a migration on DB schema change

If you want to create new model, you should import this model into `./alembic/env.py`, for example:

```python
import chat_with_anyone.models.user  # noqa
```

Create a new migration file:

```bash
alembic revision -m "<Message for migration>" --autogenerate --head head
```

## Running tests

Create the test database, then quit from the shell:

```sql
CREATE DATABASE test_chat_with_anyone;
\q
```

Running pytest:

```bash
pytest
```
