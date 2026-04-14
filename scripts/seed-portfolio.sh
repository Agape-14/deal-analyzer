#!/usr/bin/env bash
# Seed a realistic portfolio for Phase 4 testing.
# Idempotent per-run — wipe the DB first if you want a clean slate.
set -e
API=http://127.0.0.1:8000

# Developers
for name in "Summit Partners" "Acme Capital" "Pine Ridge RE"; do
  curl -s -X POST "$API/api/developers" -H "Content-Type: application/json" \
    -d "{\"name\":\"$name\"}" > /dev/null
done

# Investments (deal-less for simplicity)
curl -s -X POST "$API/api/investments/" -H "Content-Type: application/json" \
  -d '{"project_name":"Sunset Apartments","sponsor_name":"Summit Partners","investment_date":"2022-03-15","amount_invested":250000,"investment_class":"Class A","preferred_return":8,"projected_irr":16,"projected_equity_multiple":1.8,"hold_period_years":5}' > /dev/null
curl -s -X POST "$API/api/investments/" -H "Content-Type: application/json" \
  -d '{"project_name":"Riverwalk Towers","sponsor_name":"Acme Capital","investment_date":"2022-07-01","amount_invested":500000,"investment_class":"LP","preferred_return":8,"projected_irr":18,"projected_equity_multiple":2.1,"hold_period_years":5}' > /dev/null
curl -s -X POST "$API/api/investments/" -H "Content-Type: application/json" \
  -d '{"project_name":"Pine Ridge Office","sponsor_name":"Pine Ridge RE","investment_date":"2021-11-10","amount_invested":150000,"projected_irr":12,"projected_equity_multiple":1.6,"hold_period_years":3,"status":"exited","exit_date":"2024-11-15","exit_amount":240000}' > /dev/null
curl -s -X POST "$API/api/investments/" -H "Content-Type: application/json" \
  -d '{"project_name":"Harbor Lofts","sponsor_name":"Summit Partners","investment_date":"2023-02-20","amount_invested":100000,"projected_irr":15,"projected_equity_multiple":1.9,"hold_period_years":5}' > /dev/null
curl -s -X POST "$API/api/investments/" -H "Content-Type: application/json" \
  -d '{"project_name":"Mesa Flats","sponsor_name":"Acme Capital","investment_date":"2023-08-01","amount_invested":75000,"projected_irr":14,"projected_equity_multiple":1.7,"hold_period_years":5}' > /dev/null

add_dist() {
  local inv=$1 amt=$2 dt=$3
  curl -s -X POST "$API/api/investments/$inv/distributions" -H "Content-Type: application/json" \
    -d "{\"date\":\"$dt\",\"amount\":$amt,\"dist_type\":\"cash_flow\"}" > /dev/null
}

# Realistic quarterly distributions
# Sunset: 10 qtrs @ ~1.8% = $4,500
for q in $(seq 1 10); do
  dt=$(python3 -c "import datetime; print((datetime.date(2022,7,1) + datetime.timedelta(days=90*$q)).isoformat())")
  add_dist 1 4500 "$dt"
done
# Riverwalk: 10 qtrs @ ~1.8% of 500k = $9,000
for q in $(seq 1 10); do
  dt=$(python3 -c "import datetime; print((datetime.date(2022,10,1) + datetime.timedelta(days=90*$q)).isoformat())")
  add_dist 2 9000 "$dt"
done
# Pine Ridge: 8 qtrs pre-exit @ 2% = $3,000
for q in $(seq 1 8); do
  dt=$(python3 -c "import datetime; print((datetime.date(2022,2,1) + datetime.timedelta(days=90*$q)).isoformat())")
  add_dist 3 3000 "$dt"
done
# Harbor: 6 qtrs @ 1.8% = $1,800
for q in $(seq 1 6); do
  dt=$(python3 -c "import datetime; print((datetime.date(2023,6,1) + datetime.timedelta(days=90*$q)).isoformat())")
  add_dist 4 1800 "$dt"
done
# Mesa: 5 qtrs @ 1.6% = $1,200
for q in $(seq 1 5); do
  dt=$(python3 -c "import datetime; print((datetime.date(2023,12,1) + datetime.timedelta(days=90*$q)).isoformat())")
  add_dist 5 1200 "$dt"
done

echo "seeded: 5 investments + distributions"
