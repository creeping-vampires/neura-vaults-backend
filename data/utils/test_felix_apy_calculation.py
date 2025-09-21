import sys
import os

# Add project root to path to allow imports from data module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Initialize Django settings before importing Django-dependent modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

# Import Django and setup
import django
django.setup()

from data.utils.felix_apy_calculator import fetch_felix_final_calculated_apy, update_pool_params_with_extra_supply


# param field for felix pools
POOL_PARAMS = {
  "curve_steepness": "4.00000000",
  "adjustment_speed": "50.00000000",
  "target_utilization": "0.90000000",
  "initial_rate_at_target": "0.04000000",
  "min_rate_at_target": "0.00100000",
  "max_rate_at_target": "2.00000000",
  "utilization": 0.9116849540748998,
  "reserve_factor": 0.1,
  "total_supply": "73004904072258.00000000",
  "total_borrows": "66557472616359.00000000",
  "underlying_markets": [
    {
      "utilization": 0.8496,
      "supply_apy_gross": 10.1001,
      "total_supply_assets": 294738157465,
      "total_borrow_assets": 250402989083,
      "lltv": 0.77,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0xBe6727B535545C67d5cAa73dEa54865B92CF7907",
      "oracle": "0x6Bfa2792efA52c2ffe61eD6d5d56fFA35cc4dD67",
      "total_supply_shares": 289869425667749900,
      "total_borrow_shares": 245860790172181820,
      "borrow_rate": 3591312588
    },
    {
      "utilization": 0.9129,
      "supply_apy_gross": 18.7846,
      "total_supply_assets": 14294507725242,
      "total_borrow_assets": 13049424212190,
      "lltv": 0.625,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0x5555555555555555555555555555555555555555",
      "oracle": "0x8f36DF5a5a9Fc1238d03401b96Aa411D6eBcA973",
      "total_supply_shares": 13786732848932911000,
      "total_borrow_shares": 12530704368317626000,
      "borrow_rate": 5979393786
    },
    {
      "utilization": 0.9129,
      "supply_apy_gross": 18.2903,
      "total_supply_assets": 12702013064582,
      "total_borrow_assets": 11595625199219,
      "lltv": 0.77,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0x9FDBdA0A5e284c32744D2f17Ee5c74B284993463",
      "oracle": "0xcE5B111739B8b6A10fd7E9dD6a1C7DF9b653317f",
      "total_supply_shares": 12356939047793164000,
      "total_borrow_shares": 11247038613998965000,
      "borrow_rate": 5834564042
    },
    {
      "utilization": 0.9129,
      "supply_apy_gross": 2.7919,
      "total_supply_assets": 5685491207748,
      "total_borrow_assets": 5190270962202,
      "lltv": 0.625,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0x94e8396e0869c9F2200760aF0621aFd240E1CF38",
      "oracle": "0x10E8707F41fd04622EB42b6bcE857690313f5D78",
      "total_supply_shares": 5666721571623354000,
      "total_borrow_shares": 5171271853600545000,
      "borrow_rate": 956487380
    },
    {
      "utilization": 0.7653,
      "supply_apy_gross": 10.7109,
      "total_supply_assets": 70642959973,
      "total_borrow_assets": 54065260154,
      "lltv": 0.77,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0x9FD7466f987Fd4C45a5BBDe22ED8aba5BC8D72d1",
      "oracle": "0x58ff4dEEc83573510a7b8F26e7318173a473768b",
      "total_supply_shares": 68978940772208630,
      "total_borrow_shares": 52666144168858340,
      "borrow_rate": 4215890581
    },
    {
      "utilization": 0.6556,
      "supply_apy_gross": 3.9683,
      "total_supply_assets": 18120863996,
      "total_borrow_assets": 11879375019,
      "lltv": 0.77,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0x1359b05241cA5076c9F59605214f4F84114c0dE8",
      "oracle": "0x485Ad642Ab73710aF785200b1eE90b3758B3d069",
      "total_supply_shares": 17898221906757150,
      "total_borrow_shares": 11717170607735648,
      "borrow_rate": 1882361860
    },
    {
      "utilization": 0.9113,
      "supply_apy_gross": 14.6943,
      "total_supply_assets": 34626092662068,
      "total_borrow_assets": 31555308232418,
      "lltv": 0.625,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0xfD739d4e423301CE9385c1fb8850539D657C296D",
      "oracle": "0x5f5272eCaf3C9ef83697c7A0f560a8B8286108C7",
      "total_supply_shares": 34021081832389784000,
      "total_borrow_shares": 30952927678067753000,
      "borrow_rate": 4770496263
    },
    {
      "utilization": 0.9129,
      "supply_apy_gross": 5.4225,
      "total_supply_assets": 5313297431184,
      "total_borrow_assets": 4850496386074,
      "lltv": 0.625,
      "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
      "collateral_token": "0x311dB0FDe558689550c68355783c95eFDfe25329",
      "oracle": "0x7111994019abaf6955FBcCd0AF0340Fd27c6B847",
      "total_supply_shares": 5290387746208912000,
      "total_borrow_shares": 4827181094732456000,
      "borrow_rate": 1834245129
    }
  ]
}
 

# main
if __name__ == "__main__":

    felix_pool_address = '0xD4a426F010986dCad727e8dd6eed44cA4A9b7483'
    apy = fetch_felix_final_calculated_apy(felix_pool_address, POOL_PARAMS)
    print(f"Felix APY: {apy}")
    # Add extra supply and get updated parameters
    extra_supply = 100000*10**6  #
    updated_params = update_pool_params_with_extra_supply(POOL_PARAMS, extra_supply)
    # print(updated_params)

    # calculate diff between old and new params and print total
    diff = float(updated_params['total_supply']) - float(POOL_PARAMS['total_supply'])
    print(f"Total supply diff: {diff}")
    # print utilization diff
    print(f"Utilization diff: {float(updated_params['utilization']) - float(POOL_PARAMS['utilization'])}")

    felix_apy = fetch_felix_final_calculated_apy(felix_pool_address, updated_params)
    print(f"Felix APY after extra supply: {felix_apy}")
    
    
    

    