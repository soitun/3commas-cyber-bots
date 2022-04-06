#!/usr/bin/env python3
"""Cyberjunky's 3Commas bot helpers."""
import argparse
import configparser
import json
from math import fabs
import os
from socket import SO_PRIORITY
import sqlite3
import sys
import time
from pathlib import Path

from helpers.logging import Logger, NotificationHandler
from helpers.misc import check_deal, unix_timestamp_to_string, wait_time_interval
from helpers.threecommas import init_threecommas_api


def load_config():
    """Create default or load existing config file."""

    cfg = configparser.ConfigParser(strict=False)
    if cfg.read(f"{datadir}/{program}.ini"):
        return cfg

    cfg["settings"] = {
        "timezone": "Europe/Amsterdam",
        "check-interval": 120,
        "monitor-interval": 60,
        "debug": False,
        "logrotate": 7,
        "3c-apikey": "Your 3Commas API Key",
        "3c-apisecret": "Your 3Commas API Secret",
        "notifications": False,
        "notify-urls": ["notify-url1"],
    }

    cfgsectionprofitconfig = list()
    cfgsectionprofitconfig.append({
        "activation-percentage": "2.0",
        "initial-stoploss-percentage": "0.5",
        "sl-increment-factor": "0.0",
        "tp-increment-factor": "0.0",
    })
    cfgsectionprofitconfig.append({
        "activation-percentage": "3.0",
        "initial-stoploss-percentage": "2.0",
        "sl-increment-factor": "0.4",
        "tp-increment-factor": "0.4",
    })

    cfgsectionsafetyconfig = list()
    cfgsectionsafetyconfig.append({
        "activation-percentage": "-1.0",
        "initial-stoploss-percentage": "0.5",
        "sl-increment-factor": "1.0",
    })

    cfg["tsl_tp_default"] = {
        "botids": [12345, 67890],
        "profit-config": json.dumps(cfgsectionprofitconfig),
        "safety-config": json.dumps(cfgsectionsafetyconfig)
    }

    with open(f"{datadir}/{program}.ini", "w") as cfgfile:
        cfg.write(cfgfile)

    return None


def upgrade_config(thelogger, cfg):
    """Upgrade config file if needed."""

    if len(cfg.sections()) == 1:
        # Old configuration containing only one section (settings)
        logger.error(
            f"Upgrading config file '{datadir}/{program}.ini' to support multiple sections"
        )

        cfg["tsl_tp_default"] = {
            "botids": cfg.get("settings", "botids"),
            "activation-percentage": cfg.get("settings", "activation-percentage"),
            "initial-stoploss-percentage": cfg.get("settings", "initial-stoploss-percentage"),
            "sl-increment-factor": cfg.get("settings", "sl-increment-factor"),
            "tp-increment-factor": cfg.get("settings", "tp-increment-factor"),
        }

        cfg.remove_option("settings", "botids")
        cfg.remove_option("settings", "activation-percentage")
        cfg.remove_option("settings", "initial-stoploss-percentage")
        cfg.remove_option("settings", "sl-increment-factor")
        cfg.remove_option("settings", "tp-increment-factor")

        with open(f"{datadir}/{program}.ini", "w+") as cfgfile:
            cfg.write(cfgfile)

        thelogger.info("Upgraded the configuration file")

    for cfgsection in cfg.sections():
        if cfgsection.startswith("tsl_tp_"):
            if not cfg.has_option(cfgsection, "profit-config"):
                cfg.set(cfgsection, "profit-config", config.get(cfgsection, "config"))
                cfg.remove_option(cfgsection, "config")

                cfgsectionsafetyconfig = list()
                cfgsectionsafetyconfig.append({
                    "activation-percentage": "-1.0",
                    "initial-stoploss-percentage": "0.5",
                    "sl-increment-factor": "1.0",
                })

                cfg.set(cfgsection, "safety-config", json.dumps(cfgsectionsafetyconfig))

                with open(f"{datadir}/{program}.ini", "w+") as cfgfile:
                    cfg.write(cfgfile)

                thelogger.info("Upgraded section %s to have profit- and safety- config list" % cfgsection)
            elif not cfg.has_option(cfgsection, "config") and not cfg.has_option(cfgsection, "profit-config"):
                cfgsectionconfig = list()
                cfgsectionconfig.append({
                    "activation-percentage": cfg.get(cfgsection, "activation-percentage"),
                    "initial-stoploss-percentage": cfg.get(cfgsection, "initial-stoploss-percentage"),
                    "sl-increment-factor": cfg.get(cfgsection, "sl-increment-factor"),
                    "tp-increment-factor": cfg.get(cfgsection, "tp-increment-factor"),
                })

                cfg.set(cfgsection, "config", json.dumps(cfgsectionconfig))

                cfg.remove_option(cfgsection, "activation-percentage")
                cfg.remove_option(cfgsection, "initial-stoploss-percentage")
                cfg.remove_option(cfgsection, "sl-increment-factor")
                cfg.remove_option(cfgsection, "tp-increment-factor")

                with open(f"{datadir}/{program}.ini", "w+") as cfgfile:
                    cfg.write(cfgfile)

                thelogger.info("Upgraded section %s to have config list" % cfgsection)

    return cfg


def update_deal_profit(thebot, deal, new_stoploss, new_take_profit):
    """Update bot with new SL and TP."""

    bot_name = thebot["name"]
    deal_id = deal["id"]

    error, data = api.request(
        entity="deals",
        action="update_deal",
        action_id=str(deal_id),
        payload={
            "deal_id": deal_id,
            "stop_loss_percentage": new_stoploss,
            "take_profit": new_take_profit,
        },
    )
    if data:
        logger.info(
            f"Changing SL for deal {deal['pair']} ({deal_id}) on bot \"{bot_name}\"\n"
            f"Changed SL from {deal['stop_loss_percentage']}% to {new_stoploss}%. "
            f"Changed TP from {deal['take_profit']}% to {new_take_profit}%"
        )
    else:
        if error and "msg" in error:
            logger.error(
                "Error occurred updating deal with new SL/TP values: %s" % error["msg"]
            )
        else:
            logger.error("Error occurred updating deal with new SL/TP valuess")


def update_deal_add_safety_funds(thebot, deal, quantity, limit_price):
    """Update bot with new Safety Order configuration."""

    bot_name = thebot["name"]
    deal_id = deal["id"]

    error, data = api.request(
        entity="deals",
        action="add_funds",
        action_id=str(deal_id),
        payload={
            "quantity": quantity,
            "is_market": False,
            "rate": limit_price,
            "deal_id": deal_id,
        },
    )
    if data:
        logger.info(
            f"Adding funds for deal {deal['pair']} ({deal_id}) on bot \"{bot_name}\"\n"
            f"Add {quantity} at limit price {limit_price}."
        )
    else:
        if error and "msg" in error:
            logger.error(
                "Error occurred adding funds for safety to deal: %s" % error["msg"]
            )
        else:
            logger.error("Error occurred adding funds for safety to deal")


def calculate_slpercentage_base_price_short(sl_price, base_price):
    """Calculate the SL percentage of the base price for a short deal"""

    return round(
        ((sl_price / base_price) * 100.0) - 100.0,
        2
    )


def calculate_slpercentage_base_price_long(sl_price, base_price):
    """Calculate the SL percentage of the base price for a long deal"""

    return round(
        100.0 - ((sl_price / base_price) * 100.0),
        2
    )


def calculate_average_price_sl_percentage_short(sl_price, average_price):
    """Calculate the SL percentage based on the average price for a short deal"""

    return round(
        100.0 - ((sl_price / average_price) * 100.0),
        2
    )


def calculate_average_price_sl_percentage_long(sl_price, average_price):
    """Calculate the SL percentage based on the average price for a long deal"""

    return round(
        ((sl_price / average_price) * 100.0) - 100.0,
        2
    )


def get_config_for_profit(section_profit_config, current_profit):
    """Get the settings from the config corresponding to the current profit"""

    profitconfig = {}

    for entry in section_profit_config:
        if current_profit >= float(entry["activation-percentage"]):
            profitconfig = entry
        else:
            break

    logger.debug(
        f"Profit config to use based on current profit {current_profit}% "
        f"is {profitconfig}"
    )

    return profitconfig


def process_deals(thebot, section_profit_config):
    """Check deals from bot, compare against the database and handle them."""

    monitored_deals = 0

    botid = thebot["id"]
    deals = thebot["active_deals"]

    if deals:
        current_deals = []

        for deal in deals:
            deal_id = deal["id"]

            logger.info(deal)

            if deal["strategy"] in ("short", "long"):
                current_deals.append(deal_id)

                deal_db_data = check_deal(cursor, deal_id)
                actual_profit_config = get_config_for_profit(
                        section_profit_config, float(deal["actual_profit_percentage"])
                    )

                handle_safety_orders(thebot, deal, deal_db_data)

                continue;

                if not deal_db_data and actual_profit_config:
                    monitored_deals = +1

                    handle_new_deal(thebot, deal, actual_profit_config)
                elif deal_db_data:
                    deal_sl = deal["stop_loss_percentage"]
                    current_stoploss_percentage = 0.0 if deal_sl is None else float(deal_sl)
                    if current_stoploss_percentage != 0.0:
                        monitored_deals = +1

                        handle_update_deal(
                                thebot, deal, deal_db_data, actual_profit_config
                            )
                    else:
                        # Existing deal, but stoploss is 0.0 which means it has been reset
                        remove_active_deal(deal_id)
            else:
                logger.warning(
                    f"Unknown strategy {deal['strategy']} for deal {deal_id}"
                )

        # Housekeeping, clean things up and prevent endless growing database
        remove_closed_deals(botid, current_deals)

        logger.debug(
            f"Bot \"{thebot['name']}\" ({botid}) has {len(deals)} deal(s) "
            f"of which {monitored_deals} require monitoring."
        )
    else:
        logger.debug(
            f"Bot \"{thebot['name']}\" ({botid}) has no active deals."
        )
        remove_all_deals(botid)

    return monitored_deals


def calculate_sl_percentage(deal_data, profit_config, activation_diff):
    """Calculate the SL percentage in 3C range"""

    initial_stoploss_percentage = float(profit_config.get("initial-stoploss-percentage"))
    sl_increment_factor = float(profit_config.get("sl-increment-factor"))

    # SL is calculated by 3C on base order price. Because of filled SO's,
    # we must first calculate the SL price based on the average price
    average_price = 0.0
    if deal_data["strategy"] == "short":
        average_price = float(deal_data["sold_average_price"])
    else:
        average_price = float(deal_data["bought_average_price"])

    # Calculate the amount we need to substract or add to the average price based
    # on the configured increments and activation
    percentage_price = average_price * ((initial_stoploss_percentage / 100.0)
                                        + ((activation_diff / 100.0) * sl_increment_factor))

    sl_price = average_price
    if deal_data["strategy"] == "short":
        sl_price -= percentage_price
    else:
        sl_price += percentage_price

    logger.debug(
        f"{deal_data['pair']}/{deal_data['id']}: SL price {sl_price} calculated based on average "
        f"price {average_price}, initial SL of {initial_stoploss_percentage}, "
        f"activation diff of {activation_diff} and sl factor {sl_increment_factor}"
    )

    # Now we know the SL price, let's calculate the percentage from
    # the base order price so we have the desired SL for 3C
    base_price = float(deal_data["base_order_average_price"])
    base_price_sl_percentage = 0.0

    if deal_data["strategy"] == "short":
        base_price_sl_percentage = calculate_slpercentage_base_price_short(
                sl_price, base_price
            )
    else:
        base_price_sl_percentage = calculate_slpercentage_base_price_long(
                sl_price, base_price
            )

    logger.debug(
        f"{deal_data['pair']}/{deal_data['id']}: base SL of {base_price_sl_percentage}% calculated "
        f"based on base price {base_price} and SL price {sl_price}."
    )

    return average_price, sl_price, base_price_sl_percentage


def handle_new_deal(thebot, deal, profit_config):
    """New deal (short or long) to activate SL on"""

    botid = thebot["id"]
    actual_profit_percentage = float(deal["actual_profit_percentage"])

    activation_percentage = float(profit_config.get("activation-percentage"))

    # Take space between trigger and actual profit into account
    activation_diff = actual_profit_percentage - activation_percentage

    # SL data contains three values:
    # 0. The sold or bought average price
    # 1. The calculated SL price
    # 2. The SL percentage on 3C axis (inverted range compared to TP axis)
    sl_data = calculate_sl_percentage(deal, profit_config, activation_diff)

    if sl_data[2] != 0.00:
        # Calculate understandable SL percentage (TP axis range) based on average price
        average_price_sl_percentage = 0.0

        if deal["strategy"] == "short":
            average_price_sl_percentage = calculate_average_price_sl_percentage_short(
                    sl_data[1], sl_data[0]
                )
        else:
            average_price_sl_percentage = calculate_average_price_sl_percentage_long(
                    sl_data[1], sl_data[0]
                )

        logger.debug(
            f"{deal['pair']}/{deal['id']}: average SL of {average_price_sl_percentage}% "
            f"calculated based on average price {sl_data[0]} and "
            f"SL price {sl_data[1]}."
        )

        # Calculate new TP percentage
        current_tp_percentage = float(deal["take_profit"])
        new_tp_percentage = round(
            current_tp_percentage
            + (activation_diff * float(profit_config.get("tp-increment-factor"))),
            2
        )

        logger.info(
            f"\"{thebot['name']}\": {deal['pair']}/{deal['id']} "
            f"profit ({actual_profit_percentage}%) above activation ({activation_percentage}%). "
            f"StopLoss activated on {average_price_sl_percentage}%.",
            True
        )

        if new_tp_percentage > current_tp_percentage:
            logger.info(
                f"TakeProfit increased from {current_tp_percentage}% "
                f"to {new_tp_percentage}%",
                True
            )

        # Update deal in 3C
        update_deal_profit(thebot, deal, sl_data[2], new_tp_percentage)

        # Add deal to our database
        add_deal_in_db(
            deal["id"], botid, actual_profit_percentage, average_price_sl_percentage, new_tp_percentage
        )
    else:
        logger.debug(
            f"{deal['pair']}/{deal['id']}: calculated SL of {sl_data[2]} which "
            f"will cause 3C not to activate SL. No action taken!"
        )


def handle_update_deal(thebot, deal, deal_db_data, profit_config):
    """Update deal (short or long) and increase SL (Trailing SL) when profit has increased."""

    actual_profit_percentage = float(deal["actual_profit_percentage"])
    last_profit_percentage = float(deal_db_data["last_profit_percentage"])

    if actual_profit_percentage > last_profit_percentage:
        sl_increment_factor = float(profit_config.get("sl-increment-factor"))
        tp_increment_factor = float(profit_config.get("tp-increment-factor"))

        if sl_increment_factor > 0.0 or tp_increment_factor > 0.0:
            activation_diff = actual_profit_percentage - float(profit_config.get("activation-percentage"))

            # SL data contains three values:
            # 0. The sold or bought average price
            # 1. The calculated SL price
            # 2. The SL percentage on 3C axis (inverted range compared to TP axis)
            sl_data = calculate_sl_percentage(deal, profit_config, activation_diff)

            current_sl_percentage = float(deal["stop_loss_percentage"])
            if fabs(sl_data[2]) > 0.0 and sl_data[2] != current_sl_percentage:
                # Calculate understandable SL percentage (TP axis range) based on average price
                new_average_price_sl_percentage = 0.0

                if deal["strategy"] == "short":
                    new_average_price_sl_percentage = calculate_average_price_sl_percentage_short(
                            sl_data[1], sl_data[0]
                        )
                else:
                    new_average_price_sl_percentage = calculate_average_price_sl_percentage_long(
                            sl_data[1], sl_data[0]
                        )

                logger.debug(
                    f"{deal['pair']}/{deal['id']}: new average SL "
                    f"of {new_average_price_sl_percentage}% calculated "
                    f"based on average price {sl_data[0]} and "
                    f"SL price {sl_data[1]}."
                )

                logger.info(
                    f"\"{thebot['name']}\": {deal['pair']}/{deal['id']} profit increased "
                    f"from {last_profit_percentage}% to {actual_profit_percentage}%. "
                    f"StopLoss increased from {deal_db_data['last_readable_sl_percentage']}% to "
                    f"{new_average_price_sl_percentage}%. ",
                    True
                )

                # Calculate new TP percentage based on the increased profit and increment factor
                current_tp_percentage = float(deal["take_profit"])
                new_tp_percentage = round(
                    current_tp_percentage + (
                            (actual_profit_percentage - last_profit_percentage)
                            * tp_increment_factor
                        ), 2
                )

                if new_tp_percentage > current_tp_percentage:
                    logger.info(
                        f"TakeProfit increased from {current_tp_percentage}% "
                        f"to {new_tp_percentage}%",
                        True
                    )

                # Update deal in 3C
                update_deal_profit(thebot, deal, sl_data[2], new_tp_percentage)

                # Update deal in our database
                update_deal_in_db(
                    deal['id'], actual_profit_percentage, new_average_price_sl_percentage, new_tp_percentage
                )
            else:
                logger.debug(
                    f"{deal['pair']}/{deal['id']}: calculated SL of {sl_data[2]}% which "
                    f"is equal to current SL {current_sl_percentage}% or "
                    f"is 0.0 which causes 3C to deactive SL; no change made!"
                )
        else:
            logger.debug(
                f"{deal['pair']}/{deal['id']}: profit increased from {last_profit_percentage}% "
                f"to {actual_profit_percentage}%, but increment factors are 0.0 so "
                f"no change required for this deal."
            )
    else:
        logger.debug(
            f"{deal['pair']}/{deal['id']}: no profit increase "
            f"(current: {actual_profit_percentage}%, "
            f"previous: {last_profit_percentage}%). Keep on monitoring."
        )


def remove_active_deal(deal_id):
    """Remove long deal (deal SL reset by user)."""

    logger.info(
        f"Deal {deal_id} stoploss deactivated by somebody else; stop monitoring and start "
        f"in the future again if conditions are met."
    )

    db.execute(
        f"DELETE FROM deals WHERE dealid = {deal_id}"
    )

    db.commit()


def remove_closed_deals(bot_id, current_deals):
    """Remove all deals for the given bot, except the ones in the list."""

    if current_deals:
        # Remove start and end square bracket so we can properly use it
        current_deals_str = str(current_deals)[1:-1]

        logger.debug(f"Deleting old deals from bot {bot_id} except {current_deals_str}")
        db.execute(
            f"DELETE FROM deals WHERE botid = {bot_id} AND dealid NOT IN ({current_deals_str})"
        )

        db.commit()


def remove_all_deals(bot_id):
    """Remove all stored deals for the specified bot."""

    logger.debug(
        f"Removing all stored deals for bot {bot_id}."
    )

    db.execute(
        f"DELETE FROM deals WHERE botid = {bot_id}"
    )

    db.commit()


def get_bot_next_process_time(bot_id):
    """Get the next processing time for the specified bot."""

    dbrow = cursor.execute(
            f"SELECT next_processing_timestamp FROM bots WHERE botid = {bot_id}"
        ).fetchone()

    nexttime = int(time.time())
    if dbrow is not None:
        nexttime = dbrow["next_processing_timestamp"]
    else:
        # Record missing, create one
        set_bot_next_process_time(bot_id, nexttime)

    return nexttime


def set_bot_next_process_time(bot_id, new_time):
    """Set the next processing time for the specified bot."""

    logger.debug(
        f"Next processing for bot {bot_id} not before "
        f"{unix_timestamp_to_string(new_time, '%Y-%m-%d %H:%M:%S')}."
    )

    db.execute(
        f"REPLACE INTO bots (botid, next_processing_timestamp) "
        f"VALUES ({bot_id}, {new_time})"
    )

    db.commit()


def add_deal_in_db(deal_id, bot_id, tp_percentage, readable_sl_percentage, readable_tp_percentage):
    """Add deal (short or long) to database."""

    db.execute(
        f"INSERT INTO deals ("
        f"dealid, "
        f"botid, "
        f"last_profit_percentage, "
        f"last_readable_sl_percentage, "
        f"last_readable_tp_percentage) "
        f"VALUES ("
        f"{deal_id}, {bot_id}, {tp_percentage}, {readable_sl_percentage}, {readable_tp_percentage}"
        f")"
    )

    db.commit()


def update_deal_in_db(deal_id, tp_percentage, readable_sl_percentage, readable_tp_percentage):
    """Update deal (short or long) in database."""

    db.execute(
        f"UPDATE deals SET "
        f"last_profit_percentage = {tp_percentage}, "
        f"last_readable_sl_percentage = {readable_sl_percentage}, "
        f"last_readable_tp_percentage = {readable_tp_percentage} "
        f"WHERE dealid = {deal_id}"
    )

    db.commit()


###################################################################################################################################################
def handle_safety_orders(thebot, thedeal, deal_db_data):
    """Handle the Safety Orders for this deal."""

    currentTotalProfit = ((float(thedeal["current_price"]) / float(thedeal["base_order_average_price"])) * 100.0) - 100.0

    logger.info(
        f"Processing deal {thedeal['id']} with current profit {float(thedeal['actual_profit_percentage'])}%. Total is {currentTotalProfit}%. \n"
        f"Max SO: {thedeal['max_safety_orders']}, Active: {thedeal['active_safety_orders_count']}, Current active: {thedeal['current_active_safety_orders_count']}, Completed: {thedeal['completed_safety_orders_count']}"
    )

    SOData = calculate_safety_order(thebot, thedeal)

    logger.info(
        f"SO data: {SOData}..."
    )

    if SOData[0] > 0:
        logger.info("Adding safety funds for deal...")
        update_deal_add_safety_funds(thebot, thedeal, SOData[1], SOData[2])
    else:
        logger.info("No safety funds for deal required at this time")


def calculate_safety_order(thebot, deal_data):
    """Calculate the next SO order."""

    currentTotalProfit = ((float(deal_data["current_price"]) / float(deal_data["base_order_average_price"])) * 100.0) - 100.0

    SOCounter = 0
    if float(deal_data['actual_profit_percentage']) < 0.0:
        #nextSONumber = thedeal["completed_safety_orders_count"] + 1

        #"safety_order_volume"              = Safety order size
        #"safety_order_step_percentage"     = Price deviation to open safety orders (% from initial order)
        #"martingale_volume_coefficient"    = Safety order volume scale
        #"martingale_step_coefficient"      = Safety order step scale

        #NextSO_volume = float(thebot["safety_order_volume"])
        #NextSO_Percentage_Drop_From_BO_Buy_Price = float(thebot["safety_order_step_percentage"])
        #NextSO_buy_price = float(thedeal["base_order_average_price"])  * (100 - NextSO_Percentage_Drop_From_BO_Buy_Price)
        #TotalSODrop = NextSO_Percentage_Drop_From_BO_Buy_Price

        #logger.info(
        #    f"1 --- Volume: {NextSO_volume}, Drop: {NextSO_Percentage_Drop_From_BO_Buy_Price}/{TotalSODrop}, Price: {NextSO_buy_price}"
        #)
        
        #if nextSONumber > 1:
            
        #    NextSO_volume = float(thebot["safety_order_volume"])
        #    NextSO_Percentage_Drop_From_BO_Buy_Price = float(thebot["safety_order_step_percentage"])

        #SOCounter = 1
            #while i <= nextSONumber:
        #while TotalSODrop < fabs(currentTotalProfit) and SOCounter < thedeal['max_safety_orders']:
            # Add SO to list to be activated
        #    activatesafety.append(SOCounter)

            #NextSO_volume = float(NextSO_volume) * float(thebot["martingale_volume_coefficient"])
            #NextSO_Percentage_Drop_From_BO_Buy_Price = float(NextSO_Percentage_Drop_From_BO_Buy_Price) * float(thebot["martingale_step_coefficient"])
            #NextSO_buy_price = float(thedeal["base_order_average_price"]) * float((100 - NextSO_Percentage_Drop_From_BO_Buy_Price))
            #TotalSODrop += NextSO_Percentage_Drop_From_BO_Buy_Price

            #SOCounter += 1

            #logger.info(
            #    f"{SOCounter} --- Volume: {NextSO_volume}, Drop: {NextSO_Percentage_Drop_From_BO_Buy_Price}/{TotalSODrop}, Price: {NextSO_buy_price}"
            #)
        #currentTotalProfit = -50.0

        SO_Volume = 0.0
        SO_Price = 0.0
        
        # First SO, assign default configured values
        NextSO_volume = float(thebot["safety_order_volume"])
        NextSO_Percentage_Drop_From_BO_Buy_Price = float(thebot["safety_order_step_percentage"])
        NextSO_buy_price = float(deal_data["base_order_average_price"])  * ((100 - NextSO_Percentage_Drop_From_BO_Buy_Price) / 100.0)
        TotalSODrop = NextSO_Percentage_Drop_From_BO_Buy_Price

        logger.info(
            f"{SOCounter + 1} --- Volume: {NextSO_volume}, Drop: {NextSO_Percentage_Drop_From_BO_Buy_Price}/{TotalSODrop}, Price: {NextSO_buy_price}"
        )
        
        if TotalSODrop < fabs(currentTotalProfit):
            # Current (negative) profit below first SO, see how far
            logger.info(
                f"First SO drop of {TotalSODrop}% above current {currentTotalProfit}. Lets see if there are more SO to be filled..."
            )

            SO_Volume = NextSO_volume
            SO_Price = NextSO_buy_price
        
            SOCounter = 1
            while SOCounter < deal_data['max_safety_orders']:
                NextSO_volume = float(NextSO_volume) * float(thebot["martingale_volume_coefficient"])
                NextSO_Percentage_Drop_From_BO_Buy_Price = float(NextSO_Percentage_Drop_From_BO_Buy_Price) * float(thebot["martingale_step_coefficient"])
                TotalSODrop += NextSO_Percentage_Drop_From_BO_Buy_Price
                NextSO_buy_price = float(deal_data["base_order_average_price"])  * ((100 - TotalSODrop) / 100.0)

                logger.info(
                    f"Calculated {SOCounter + 1} --- Volume: {NextSO_volume}, Drop: {NextSO_Percentage_Drop_From_BO_Buy_Price}/{TotalSODrop}, Price: {NextSO_buy_price}"
                )

                if TotalSODrop > fabs(currentTotalProfit):
                    # Last calculated SO is below current (negative) profit, so stop here
                    logger.info(f"Break from loop at {SOCounter}")
                    break;
                else:
                    # SO is still above current (negative) profit, so calculate the next one
                    SO_Volume += NextSO_volume
                    SO_Price = NextSO_buy_price
            
                    SOCounter += 1
                    logger.info(f"Continue in loop, now at SO {SOCounter}")
        
        logger.info(
            f"SO level {SOCounter} reached {SO_Volume}/{SO_Price}!"
        )
    
    return SOCounter, SO_Volume, SO_Price



#######################################################################################################################################################

def open_tsl_db():
    """Create or open database to store bot and deals data."""

    try:
        dbname = f"{program}.sqlite3"
        dbpath = f"file:{datadir}/{dbname}?mode=rw"
        dbconnection = sqlite3.connect(dbpath, uri=True)
        dbconnection.row_factory = sqlite3.Row

        logger.info(f"Database '{datadir}/{dbname}' opened successfully")

    except sqlite3.OperationalError:
        dbconnection = sqlite3.connect(f"{datadir}/{dbname}")
        dbconnection.row_factory = sqlite3.Row
        dbcursor = dbconnection.cursor()
        logger.info(f"Database '{datadir}/{dbname}' created successfully")

        dbcursor.execute(
            "CREATE TABLE IF NOT EXISTS deals ("
            "dealid INT Primary Key, "
            "botid INT, "
            "last_profit_percentage FLOAT, "
            "last_readable_sl_percentage FLOAT, "
            "last_readable_tp_percentage FLOAT "
            ")"
        )

        dbcursor.execute(
            "CREATE TABLE IF NOT EXISTS bots ("
            "botid INT Primary Key, "
            "next_processing_timestamp INT"
            ")"
        )

        logger.info("Database tables created successfully")

    return dbconnection


def upgrade_trailingstoploss_tp_db():
    """Upgrade database if needed."""
    try:
        try:
            # DROP column supported from sqlite 3.35.0 (2021.03.12)
            cursor.execute("ALTER TABLE deals DROP COLUMN last_stop_loss_percentage")
        except sqlite3.OperationalError:
            logger.debug("Older SQLite version; not used column not removed")

        cursor.execute("ALTER TABLE deals ADD COLUMN last_readable_sl_percentage FLOAT")
        cursor.execute("ALTER TABLE deals ADD COLUMN last_readable_tp_percentage FLOAT")

        cursor.execute(
            "CREATE TABLE IF NOT EXISTS bots ("
            "botid INT Primary Key, "
            "next_processing_timestamp INT"
            ")"
        )

        logger.info("Database schema upgraded")
    except sqlite3.OperationalError:
        logger.debug("Database schema is up-to-date")


# Start application
program = Path(__file__).stem

# Parse and interpret options.
parser = argparse.ArgumentParser(description="Cyberjunky's 3Commas bot helper.")
parser.add_argument("-d", "--datadir", help="data directory to use", type=str)

args = parser.parse_args()
if args.datadir:
    datadir = args.datadir
else:
    datadir = os.getcwd()

# Create or load configuration file
config = load_config()
if not config:
    # Initialise temp logging
    logger = Logger(datadir, program, None, 7, False, False)
    logger.info(
        f"Created example config file '{datadir}/{program}.ini', edit it and restart the program"
    )
    sys.exit(0)
else:
    # Handle timezone
    if hasattr(time, "tzset"):
        os.environ["TZ"] = config.get(
            "settings", "timezone", fallback="Europe/Amsterdam"
        )
        time.tzset()

    # Init notification handler
    notification = NotificationHandler(
        program,
        config.getboolean("settings", "notifications"),
        config.get("settings", "notify-urls"),
    )

    # Initialise logging
    logger = Logger(
        datadir,
        program,
        notification,
        int(config.get("settings", "logrotate", fallback=7)),
        config.getboolean("settings", "debug"),
        config.getboolean("settings", "notifications"),
    )

    # Upgrade config file if needed
    config = upgrade_config(logger, config)

    logger.info(f"Loaded configuration from '{datadir}/{program}.ini'")

# Initialize 3Commas API
api = init_threecommas_api(config)

# Initialize or open the database
db = open_tsl_db()
cursor = db.cursor()

# Upgrade the database if needed
upgrade_trailingstoploss_tp_db()

# TrailingStopLoss and TakeProfit %
while True:

    config = load_config()
    logger.info(f"Reloaded configuration from '{datadir}/{program}.ini'")

    # Configuration settings
    check_interval = int(config.get("settings", "check-interval"))
    monitor_interval = int(config.get("settings", "monitor-interval"))

    # Used to determine the correct interval
    deals_to_monitor = 0

    # Current time to determine which bots to process
    starttime = int(time.time())

    for section in config.sections():
        if section.startswith("tsl_tp_"):
            # Bot configuration for section
            botids = json.loads(config.get(section, "botids"))

            # Get and check the config for this section
            sectionprofitconfig = json.loads(config.get(section, "profit-config"))
            if len(sectionprofitconfig) == 0:
                logger.warning(
                    f"Section {section} has an empty \'config\'. Skipping this section!"
                )
                continue

            # Walk through all bots configured
            for bot in botids:
                nextprocesstime = get_bot_next_process_time(bot)

                # Only process the bot if it's time for the next interval, or
                # time exceeds the check interval (clock has changed somehow)
                if starttime >= nextprocesstime or (
                        abs(nextprocesstime - starttime) > check_interval
                ):
                    boterror, botdata = api.request(
                        entity="bots",
                        action="show",
                        action_id=str(bot),
                    )
                    if botdata:
                        bot_deals_to_monitor = process_deals(botdata, sectionprofitconfig)

                        # Determine new time to process this bot, based on the monitored deals
                        newtime = starttime + (
                                check_interval if bot_deals_to_monitor == 0 else monitor_interval
                            )
                        set_bot_next_process_time(bot, newtime)

                        deals_to_monitor += bot_deals_to_monitor
                    else:
                        if boterror and "msg" in boterror:
                            logger.error("Error occurred updating bots: %s" % boterror["msg"])
                        else:
                            logger.error("Error occurred updating bots")
                else:
                    logger.debug(
                        f"Bot {bot} will be processed after "
                        f"{unix_timestamp_to_string(nextprocesstime, '%Y-%m-%d %H:%M:%S')}."
                    )

    timeint = check_interval if deals_to_monitor == 0 else monitor_interval
    if not wait_time_interval(logger, notification, timeint, False):
        break
