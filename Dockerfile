FROM python:3.6

# Install Python dependencies
RUN pip install pipenv

COPY Pipfile /code/
COPY Pipfile.lock /code/

WORKDIR /code

RUN cd /code/ && pipenv install -d

COPY . /code

# RUN pipenv run ./manage.py collectstatic --noinput

ENV PYTHONPATH /code

# Run the green unicorn
CMD pipenv run gunicorn -w 4 -b 0.0.0.0:8040 --name offenegesetze_gunicorn \
  --log-level info --log-file /var/log/gunicorn.log offenegesetze.wsgi:application
