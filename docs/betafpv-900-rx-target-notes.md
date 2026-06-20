# BETAFPV 900 RX target notes

## Baseline

- ExpressLRS version: 3.3.1
- Environment: BETAFPV_900_RX_via_UART
- Regulatory domain: FCC915
- Build status: SUCCESS

## Available BETAFPV 900 RX envs in ExpressLRS 3.3.1

- BETAFPV_900_RX_via_UART
- BETAFPV_900_RX_via_BetaflightPassthrough
- BETAFPV_900_RX_via_WIFI

## Important note

BETAFPV_900_RX_via_UART extends Unified_ESP8285_900_RX_via_UART.

So this baseline is for the classic ESP8285 BETAFPV 900 RX target.

If the physical receiver is actually an ESP32-based BETAFPV SuperD/SuperP 900 RX, it must be handled separately through the unified ESP32 900 RX target family.
