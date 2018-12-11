# Generated by Django 2.0.7 on 2018-08-20 08:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_kubemetric_cumulative'),
    ]

    operations = [
        migrations.AddField(
            model_name='modelrun',
            name='cpu_limit',
            field=models.CharField(default='12000m', max_length=20),
        ),
        migrations.AddField(
            model_name='modelrun',
            name='num_workers',
            field=models.IntegerField(default=2),
        ),
    ]
