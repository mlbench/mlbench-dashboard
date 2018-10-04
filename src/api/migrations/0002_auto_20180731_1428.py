# Generated by Django 2.0.7 on 2018-07-31 14:28

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='KubeMetric',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('date', models.DateTimeField()),
                ('value', models.CharField(max_length=100)),
                ('metadata', models.TextField()),
            ],
        ),
        migrations.AddField(
            model_name='kubepod',
            name='node_name',
            field=models.CharField(default='node1', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='kubemetric',
            name='pod',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='metrics',
                to='api.KubePod'),
        ),
    ]
