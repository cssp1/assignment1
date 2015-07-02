#!/bin/bash

GAME_DIR=/home/ec2-user/thunderrun
cd ${GAME_DIR}/gameserver

(for KIND in bx br bs; do \
  ./skynet.py --mode adgroups-delete --filter ${KIND}_u4 --max-freq 10 --min-age 14400 > /dev/null && \
  ./skynet.py --mode adgroups-delete --filter ${KIND}_u32 --max-frequency 2 --min-age 14400 > /dev/null; \
done) && \
./skynet.py --mode adcampaigns-collect-garbage > /dev/null
