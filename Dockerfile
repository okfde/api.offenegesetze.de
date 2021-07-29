FROM python:3.8

RUN apt-get update && apt-get install -y qpdf poppler-utils

# Install Python dependencies

COPY requirements.txt /code/

WORKDIR /code

RUN cd /code/ && python -m pip install -r requirements.txt

COPY . /code

ENV PYTHONPATH /code
RUN python manage.py collectstatic --noinput

# Run the green unicorn
CMD python manage.py collectstatic --noinput && gunicorn -w 4 -b 0.0.0.0:8045 --name offenegesetze_gunicorn \
  --log-level info --log-file /var/log/gunicorn.log offenegesetze.wsgi:application
