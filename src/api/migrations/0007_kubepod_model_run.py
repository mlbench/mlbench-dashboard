# Generated by Django 2.0.7 on 2018-08-27 10:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0006_auto_20180820_0846"),
    ]

    operations = [
        migrations.AddField(
            model_name="kubepod",
            name="model_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pods",
                to="api.ModelRun",
            ),
        ),
    ]
