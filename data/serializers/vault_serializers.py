from rest_framework import serializers
from data.models import VaultPrice, VaultAPY


class VaultPriceSerializer(serializers.ModelSerializer):
    """Serializer for the VaultPrice model with additional APY data"""
    
    # Add fields for 24h and 7d APY data
    apy_24h = serializers.SerializerMethodField()
    apy_7d = serializers.SerializerMethodField()
    
    class Meta:
        model = VaultPrice
        fields = [
            'id', 
            'vault_address', 
            'token',
            'protocol',
            'pool_apy', 
            'share_price', 
            'share_price_formatted', 
            'total_assets', 
            'total_supply',
            'apy_24h',
            'apy_7d',
            'created_at'
        ]
        read_only_fields = fields
    
    def get_apy_24h(self, obj):
        """Get the latest 24h APY for this vault"""
        latest_apy = VaultAPY.objects.filter(
            vault_address=obj.vault_address,
            token=obj.token
        ).order_by('-calculation_time').first()
        
        if latest_apy and latest_apy.apy_24h is not None:
            return float(latest_apy.apy_24h)
        return None
    
    def get_apy_7d(self, obj):
        """Get the latest 7d APY for this vault"""
        latest_apy = VaultAPY.objects.filter(
            vault_address=obj.vault_address,
            token=obj.token
        ).order_by('-calculation_time').first()
        
        if latest_apy and latest_apy.apy_7d is not None:
            return float(latest_apy.apy_7d)
        return None


class VaultPriceChartSerializer(serializers.ModelSerializer):
    """Serializer for VaultPrice data used in charts"""
    
    timestamp = serializers.DateTimeField(source='created_at')
    apy_24h = serializers.SerializerMethodField()
    apy_7d = serializers.SerializerMethodField()
    
    class Meta:
        model = VaultPrice
        fields = [
            'timestamp',
            'token',
            'share_price_formatted',
            'pool_apy',
            'apy_24h',
            'apy_7d'
        ]
    
    def get_apy_24h(self, obj):
        """Get the 24h APY for this vault at this timestamp"""
        # Find the closest VaultAPY record to this timestamp
        closest_apy = VaultAPY.objects.filter(
            vault_address=obj.vault_address,
            token=obj.token,
            calculation_time__lte=obj.created_at
        ).order_by('-calculation_time').first()
        
        if closest_apy and closest_apy.apy_24h is not None:
            return float(closest_apy.apy_24h)
        return None
    
    def get_apy_7d(self, obj):
        """Get the 7d APY for this vault at this timestamp"""
        # Find the closest VaultAPY record to this timestamp
        closest_apy = VaultAPY.objects.filter(
            vault_address=obj.vault_address,
            token=obj.token,
            calculation_time__lte=obj.created_at
        ).order_by('-calculation_time').first()
        
        if closest_apy and closest_apy.apy_7d is not None:
            return float(closest_apy.apy_7d)
        return None
