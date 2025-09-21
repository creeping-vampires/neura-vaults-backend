from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0005_vaultapy'),
    ]

    operations = [
        migrations.CreateModel(
            name='VaultDepositRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('success', 'Success'), ('failed', 'Failed'), ('skipped', 'Skipped')], max_length=10)),
                ('vault_address', models.CharField(max_length=42)),
                ('asset_address', models.CharField(max_length=42)),
                ('asset_symbol', models.CharField(max_length=10)),
                ('asset_decimals', models.IntegerField(default=18)),
                ('queue_length_before', models.IntegerField(default=0)),
                ('queue_length_after', models.IntegerField(default=0)),
                ('processed_count', models.IntegerField(default=0)),
                ('batch_size', models.IntegerField(default=5)),
                ('total_assets_to_deposit', models.BigIntegerField(default=0)),
                ('idle_assets_before', models.BigIntegerField(default=0)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('execution_duration_seconds', models.FloatField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='VaultDepositTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_hash', models.CharField(max_length=66)),
                ('gas_used', models.IntegerField(default=0)),
                ('status', models.CharField(choices=[('success', 'Success'), ('failed', 'Failed'), ('pending', 'Pending')], max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='data.vaultdepositrun')),
            ],
        ),
    ]
