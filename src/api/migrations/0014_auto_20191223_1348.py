# Generated by Django 2.0.8 on 2019-12-23 13:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0013_modelrun_light_target'),
    ]

    operations = [
        migrations.AlterField(
            model_name='kubemetric',
            name='value',
            field=models.CharField(max_length=255),
        ),
    ]
