# Generated by Django 2.1 on 2018-08-14 10:07

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Publication',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('bgbl1', 'BGBL I'), ('bgbl2', 'BGBL II')], max_length=25)),
                ('year', models.PositiveIntegerField()),
                ('number', models.PositiveIntegerField()),
                ('date', models.DateField()),
                ('page', models.PositiveIntegerField(blank=True, null=True)),
            ],
            options={
                'ordering': ('kind', 'number'),
            },
        ),
        migrations.CreateModel(
            name='PublicationEntry',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField()),
                ('title', models.TextField(blank=True)),
                ('law_date', models.DateField(blank=True, null=True)),
                ('page', models.PositiveIntegerField(blank=True, null=True)),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='bgbl.Publication')),
            ],
            options={
                'ordering': ('page',),
            },
        ),
    ]
