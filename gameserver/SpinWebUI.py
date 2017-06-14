# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for HTML/JavaScript web UI for internal analytics tools

# this requires external access to file not shipped in this package:
# SP3RDPARTY : Ext.js library : http://www.sencha.com/legal/open-source-faq/open-source-license-exception-for-applications/
# SP3RDPARTY : jquery library : MIT License

# get fast JSON library if available
try: import simplejson as json
except: import json

import string, sys, time
import SpinConfig

# indexed from 0 for JavaScript
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

class PageContent (object):
    def write_head(self, fd): pass
    def write_head_script(self, fd): pass
    def write_body(self, fd): pass


class JQueryUI (PageContent):
    def __init__(self, args = {}, campaign_list = [], gamedata = None):
        self.args = args
        self.campaign_list = campaign_list
        self.gamedata = gamedata
        self.abtests = gamedata['abtests']


    def write_head(self, fd):
#        fd.write('<script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/jquery/1.7.2/jquery.min.js"></script>\n')
#        fd.write('<script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/jqueryui/1.8.18/jquery-ui.min.js"></script>\n')
        EXT_JS_VERSION = '4.2.1' # 4.0.7
        fd.write('<script type="text/javascript" src="https://'+SpinConfig.config['public_s3_bucket']+'.s3.amazonaws.com/ext-'+EXT_JS_VERSION+'/ext-all.js"></script>\n')
        fd.write('<link rel="stylesheet" type="text/css" href="https://'+SpinConfig.config['public_s3_bucket']+'.s3.amazonaws.com/ext-'+EXT_JS_VERSION+'/resources/css/ext-all.css" />\n')

        # manually override a little CSS bug in Ext.js that causes scrollbars to appear on the little tab headers in Chrome
        fd.write('''<style type="text/css">
        .x-tab button { overflow-x: hidden }
        </style>
        ''')


    def write_head_script(self, fd):
        ages = [{'boxLabel': 'Unknown', 'name': 'age_group', 'inputValue': 'MISSING', 'checked': True}] + \
               [{'boxLabel': val, 'name': 'age_group', 'inputValue': key, 'checked': True} for key, val in \
                sorted(SpinConfig.AGE_GROUPS.items(), key = lambda kv: int(kv[0].split('O')[1]))]
        fd.write('var spin_age_groups = '+json.dumps(ages)+';\n')

        browsers = [{'boxLabel': 'Any', 'name': 'browser_name', 'inputValue': 'ANY', 'checked': True}] + \
        [{'boxLabel': label, 'name': 'browser_name', 'inputValue': value, 'checked': False} for label, value in \
         (('Chrome', 'Chrome'), ('IE', 'Explorer'), ('Firefox', 'Firefox'), ('Safari', 'Safari'), ('Opera', 'Opera'))]
        fd.write('var spin_browser_names = '+json.dumps(browsers)+';\n')

        camp = {'fields':['acquisition_campaign'], 'data': [{'acquisition_campaign':n} for n in self.campaign_list]}
        fd.write('var spin_campaigns = '+json.dumps(camp)+';\n')
        abt = [{'xtype':'radiogroup', 'fieldLabel':'Test', 'name': 'overlay_abtest',
                'labelWidth': 30, 'width': 225, 'columns': 1,
                'items':[{'boxLabel':'None', 'name': 'overlay_abtest', 'inputValue': 'none', 'checked':True}] + \
                [{'boxLabel':data.get('ui_name', test_name), 'name': 'overlay_abtest', 'inputValue': test_name} for test_name, data in \
                 sorted(self.abtests.items(), key = lambda ndat: ndat[0]) \
                 if data.get('show_in_analytics', data['active'])]
                }]
        fd.write('var spin_abtests = '+json.dumps(abt)+';\n')

        reg = [{'xtype':'checkboxgroup', 'name': 'home_region',
                'labelWidth': 30, 'width': 225, 'columns': 1,
                'items':[{'boxLabel':'Not on map', 'name':'home_region', 'inputValue':'MISSING', 'checked':True}] + \
                [{'boxLabel':data['ui_name'], 'name':'home_region', 'inputValue':data['id'], 'checked':True} for id, data in sorted(self.gamedata['regions'].items(), key = lambda id_data: '%09d%s' % (id_data[1].get('ui_priority',0), id_data[1]['ui_name']))]
                }]
        fd.write('var spin_regions = '+json.dumps(reg)+';\n')

        techs = [{'xtype':'checkboxgroup', 'fieldLabel':'Require', 'name': 'require_tech',
                'labelWidth': 100, 'width': 225, 'columns': 1,
                'items': \
                [{'boxLabel':data['ui_name'], 'name': 'tech:'+tech_name, 'inputValue': '1'} for tech_name, data in \
                 sorted([kv for kv in self.gamedata['tech'].iteritems() if ('associated_unit' in kv[1])], key = lambda ndat: ndat[0]) ]
                }]
        fd.write('var spin_techs = '+json.dumps(techs)+';\n')

        fd.write('var townhall = "'+self.gamedata['townhall']+'";\n')
        fd.write('var spin_game_id_long = "'+self.gamedata['strings']['game_name']+'";\n')
        fd.write('var public_s3_bucket = "'+SpinConfig.config['public_s3_bucket']+'";\n')

        #for line in open('ext-Line-patch.js').xreadlines():
        #    fd.write(line)

        fd.write('''

        var myform_submit_ui = function() { document.getElementById("output_mode").value = "ui"; document.getElementById("myform").submit(); };
        var myform_submit_csv = function() { document.getElementById("output_mode").value = "csv"; document.getElementById("myform").submit(); };

        //Ext.QuickTips.init();
        Ext.tip.QuickTipManager.init();

        var spin_form_mutex = false;
        var spin_form_mask = null;

        // ignore data fields that have to do with the X axis or tooltips
        var grdata_field_name_is_valid = function(name) { return (name.indexOf('xname') != 0 && (name.length < 4 || name.indexOf('_tip') != (name.length-4))); };

        // convert graph results to CSV
        var grdata_to_csv = function(grdata) {
            var ret = '"'+grdata['title']+'"\\n';
            var example = grdata['data'][0];
            ret += grdata['x_format'];
            var series = [];
            for(var colname in example) {
                if(grdata_field_name_is_valid(colname)) {
                    series.push(colname);
                }
            }
            series.sort();
            for(var col = 0; col < series.length; col++) {
                ret += ','+'"'+series[col]+'"';
            }
            ret += '\\n';
            for(var row = 0; row < grdata['data'].length; row++) {
                var sample = grdata['data'][row];
                if('xname_human_local' in sample) {
                    // use preformatted Excel-style time string instead of UNIX timestamp
                    ret += sample['xname_human_local'].toString();
                } else {
                    ret += sample['xname'].toString();
                }
                for(var col = 0; col < series.length; col++) {
                    var samp = sample[series[col]];
                    var s;
                    if(samp === false) {
                        s = '';
                    } else {
                        s = samp.toString();
                    }
                    ret += ','+s;
                }
                ret += '\\n';
            }
            return ret;
        };

        // convert Funnel results to CSV
        var funnel_to_csv = function(funnel, format) {
            console.log(format);
            var ret = '"cohort"';
            for(var col = 0; col < funnel.length; col++) {
                 var stage_name = funnel[col]['stage'];
                 if(format != 'ALL' && stage_name[0] != 'A') { continue; } // ignore stages that do not begin with A
                 ret += ',"'+funnel[col]['stage']+'"';
            }
            ret += '\\n';
            for(var row = 0; row < funnel[0]['cohorts'].length; row++) {
                ret += '"'+funnel[0]['cohorts'][row]['name']+'"';
                for(var col = 0; col < funnel.length; col++) {
                    var stage_name = funnel[col]['stage'];
                    if(format != 'ALL' && stage_name[0] != 'A') { continue; } // ignore stages that do not begin with A
                    var cohort = funnel[col]['cohorts'][row];
                    var val;
                    if(cohort['N'] < 1) {
                        val = '';
                    } else if(stage_name == "A00 Account Created") {
                        val = cohort['N']; // special case
                    } else if('yes' in cohort) {
                        val = (cohort['yes']/cohort['N']).toFixed(3);
                    } else if('value' in cohort) {
                        val = cohort['value'].toFixed(3);
                    }
                    ret += ','+val;
                }
                ret += '\\n';
            }
            return ret;
        };

        // from http://javascript.about.com/library/bldst.htm
        var spin_stdTimezoneOffset = function(d) {
            var jan = new Date(d.getFullYear(), 0, 1);
            var jul = new Date(d.getFullYear(), 6, 1);
            return Math.max(jan.getTimezoneOffset(), jul.getTimezoneOffset());
        };
        var spin_is_dst = function (d) {
            return d.getTimezoneOffset() < spin_stdTimezoneOffset(d);
        };

        Ext.onReady(function(){
        spin_form_mask = new Ext.LoadMask(Ext.getBody(), {msg:"Processing..."});

        var mypage = Ext.create('Ext.Viewport', {
        layout: 'border',
        items: [
        Ext.create('Ext.form.Panel', {
              region:'west',
              id:'my_form',
              width:285, bodyPadding: 10,
              title: spin_game_id_long.toUpperCase(),
              layout: { type: 'vbox', align: 'left', autoSize:true },

              autoScroll: true,
              //layout: { type: 'vbox', padding: '10', align: 'left', pack: 'start', autoSize: true }, // align: 'stretch'


              items: [{
                 xtype: 'checkboxgroup', fieldLabel: 'Country Tier', name: 'country_tier',
                 columns: 4, vertical: true, width:250, labelWidth: 120,
                 items: [{ 'boxLabel': '1', 'name': 'country_tier', 'inputValue': '1', checked:true },
                         { 'boxLabel': '2', 'name': 'country_tier', 'inputValue': '2', checked:true },
                         { 'boxLabel': '3', 'name': 'country_tier', 'inputValue': '3', checked:true },
                         { 'boxLabel': '4', 'name': 'country_tier', 'inputValue': '4', checked:true }]
                  },
//                  {xtype: 'checkboxgroup', fieldLabel: 'Price Region', name: 'price_region',
//                  columns: 4, vertical: true, width:250, labelWidth: 120,
//                 items: [{ 'boxLabel': 'A', 'name': 'price_region', 'inputValue': 'A', checked:true },
//                         { 'boxLabel': 'B', 'name': 'price_region', 'inputValue': 'B', checked:true },
//                         { 'boxLabel': 'C', 'name': 'price_region', 'inputValue': 'C', checked:true },
//                         { 'boxLabel': 'D', 'name': 'price_region', 'inputValue': 'D', checked:true }]
//                  },
                  { xtype: 'panel', title: 'Age Groups', id: 'age_group_panel',
                    bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    collapsible: true, collapsed: false, forceLayout: true, items: [
                    { xtype: 'checkboxgroup', fieldLabel: 'Show Groups', name: 'age_group',
                    columns: 1, vertical: true, width:242, labelWidth: 140,
                    items: spin_age_groups
                    }]
                  },
                  { xtype: 'panel', title: 'Web Browsers', id: 'browser_panel',
                    bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    collapsible: true, collapsed: false, forceLayout: true, items: [
                    { xtype: 'radiogroup', fieldLabel: 'Show Only', name: 'browser_name',
                    columns: 1, vertical: true, width:242, labelWidth: 140,
                    items: spin_browser_names
                    }]
                  },
                  { xtype: 'combobox', fieldLabel: 'Campaign', store: Ext.create('Ext.data.Store', spin_campaigns),
                    width:250, autoSelect: true,
                    querymode: 'local', displayField: 'acquisition_campaign', valueField: 'acquisition_campaign', 'name': 'acquisition_campaign', 'value': 'ALL'
                  },

                  { xtype: 'textfield', fieldLabel: 'Skynet Filter', width:250, name: 'acquisition_ad_skynet2', value:'' },
                  { xtype: 'textfield', fieldLabel: 'Skynet Params', width:250, name: 'acquisition_ad_skynet', value:'' },

                  { xtype: 'textfield', fieldLabel: 'Country', width:250, name: 'country', value:'' },

                  { xtype: 'numberfield', fieldLabel: 'Join Week', width:250, name: 'join_week', allowDecimals: false, minValue:0, value:'' },

                 { xtype: 'numberfield', fieldLabel: 'User Receipts >=', width:250, name: 'money_spent_min', allowDecimals: true, minValue:0, value:'' },
                 { xtype: 'numberfield', fieldLabel: 'User Receipts <', width:250, name: 'money_spent_max', allowDecimals: true, minValue:0, value:'' },
                 { xtype: 'numberfield', fieldLabel: 'Current Level >=', width:250, name: 'player_level_min', allowDecimals: true, minValue:0, value:'' },
                 { xtype: 'numberfield', fieldLabel: 'Current Level <', width:250, name: 'player_level_max', allowDecimals: true, minValue:0, value:'' },

                  { xtype: 'datefield', fieldLabel: 'Accounts Created After', 'name': 'account_creation_min',
                    maxValue: Ext.Date.add(new Date(), Ext.Date.DAY, 3), // future
                    value: '', labelWidth:140, width:250 },
                  { xtype: 'datefield', fieldLabel: 'Accounts Created Before', 'name': 'account_creation_max',
                    value: '', // tomorrow
                    maxValue: Ext.Date.add(new Date(), Ext.Date.DAY, 3), // future
                    labelWidth:140, width:250
                    },

                  { xtype: 'datefield', fieldLabel: 'Graph Start', 'name': 'graph_time_min', maxValue: new Date(),
                    value: (function() { var d = new Date(); d.setDate(d.getDate()-30); return d; })(), labelWidth:140, width:250 },
                  { xtype: 'datefield', fieldLabel: 'Graph End', 'name': 'graph_time_max',
                    value:    '', // tomorrow
                    maxValue: Ext.Date.add(new Date(), Ext.Date.DAY, 3), // future
                    labelWidth:140, width:250
                    },
                  { xtype: 'datefield', fieldLabel: 'Pretend Now Is', 'name': 'alter_now',
                    value:    '', // tomorrow
                    maxValue: Ext.Date.add(new Date(), Ext.Date.DAY, 3), // future
                    labelWidth:140, width:250
                    },

                  { xtype: 'radiogroup', fieldLabel: 'Compare', name: 'overlay_mode',
                    columns: 1, vertical: true, width:250,
                    items: [{ boxLabel: 'None', name: 'overlay_mode', inputValue: 'none', checked:true },
                            { boxLabel: 'Week Ago', name: 'overlay_mode', inputValue: 'week_ago' },
                            { boxLabel: 'Month Ago', name: 'overlay_mode', inputValue: 'month_ago' },
                            { boxLabel: 'Spend Level', name: 'overlay_mode', inputValue: 'spend_level' },
//                            { boxLabel: 'Num Visits', name: 'overlay_mode', inputValue: 'logged_in_times' },
//                            { boxLabel: 'Alloys/FBCredits', name: 'overlay_mode', inputValue: 'currency' },
                            { boxLabel: 'Ad Campaign', name: 'overlay_mode', inputValue: 'acquisition_campaign' },
                            { boxLabel: 'Paid/Free Acq.', name: 'overlay_mode', inputValue: 'acquisition_paid_or_free' },
//                            { boxLabel: 'Ad Image', name: 'overlay_mode', inputValue: 'acquisition_ad_image' },
//                            { boxLabel: 'Ad Title', name: 'overlay_mode', inputValue: 'acquisition_ad_title' },
//                            { boxLabel: 'Ad Text', name: 'overlay_mode', inputValue: 'acquisition_ad_text' },
//                            { boxLabel: 'Ad Target', name: 'overlay_mode', inputValue: 'acquisition_ad_target' },
                            { boxLabel: 'Skynet Params', name: 'overlay_mode', inputValue: 'acquisition_ad_skynet' },
                            { boxLabel: 'Country Tier', name: 'overlay_mode', inputValue: 'country_tier' },
                            { boxLabel: 'Country (list above)', name: 'overlay_mode', inputValue: 'country' },
//                            { boxLabel: 'Price Region', name: 'overlay_mode', inputValue: 'price_region' },
//                            { boxLabel: 'Join Day - Accts Created!', name: 'overlay_mode', inputValue: 'join_day' },
                            { boxLabel: 'Join Week', name: 'overlay_mode', inputValue: 'join_week' },
                            { boxLabel: 'Join Month', name: 'overlay_mode', inputValue: 'join_month' },
                            { boxLabel: 'Current CC Level', name: 'overlay_mode', inputValue: townhall+'_level' },
//                            { boxLabel: 'Current Player Level', name: 'overlay_mode', inputValue: 'player_level' },
                            { boxLabel: 'Age Group', name: 'overlay_mode', inputValue: 'age_group' },
                            { boxLabel: 'Web Browser', name: 'overlay_mode', inputValue: 'browser_name' },
                            { boxLabel: 'Login Platform', name: 'overlay_mode', inputValue: 'frame_platform' }
//                            { boxLabel: 'Map Region', name: 'overlay_mode', inputValue: 'home_region' },
//                            { boxLabel: 'Active A/B Tests', name: 'overlay_mode', inputValue: 'active_abtests' }
                            ]
                  },

                  { xtype: 'numberfield', fieldLabel: 'Ignore if N below', width:250, name: 'N_min', allowDecimals: false, minValue:1, value:1 },
                  { xtype: 'panel', id:'abtest_panel', width:250,
                    title: 'A/B Tests', bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    items: spin_abtests, collapsible: true, collapsed: false, forceLayout: true },

                  { xtype: 'panel', id:'regions_panel', width:250,
                    title: 'Map Region (as of today)', bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    items: spin_regions, unused: [{xtype: 'checkboxgroup', fieldLabel: 'Show Regions', name: 'home_region',
                            columns:1, vertical:true, width:242, labelWidth: 140, items: spin_regions}],
                    collapsible: true, collapsed: false, forceLayout: true },

//                  { xtype: 'panel', id:'currencies_panel', width:250,
//                    title: 'Currencies', bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
//                    collapsible: true, collapsed: false, forceLayout: true,
//                    items: [
//                    { xtype: 'checkbox', fieldLabel: 'Include FB Credits Users', name: 'show_fbcredits', uncheckedValue: 'off', labelWidth: 220, checked:true },
//                    { xtype: 'checkbox', fieldLabel: 'Include Alloys Users', name: 'show_gamebucks', uncheckedValue: 'off', labelWidth: 220, checked:true }
//                    ] },

                  { xtype: 'panel', id:'frame_platform_panel',
                    title: 'Login Platform', bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    collapsible: true, collapsed: false, forceLayout: true, items: [
                      { xtype: 'radiogroup', fieldLabel: 'Show Only', name: 'browser_name',
                      columns: 1, vertical: true, width:242, labelWidth: 140, items: [
                      { boxLabel: 'Any', name: 'frame_platform', inputValue: 'ANY', labelWidth: 220, checked:true },
                      { boxLabel: 'Armor Games', name: 'frame_platform', inputValue: 'ag', labelWidth: 220, checked:false },
                      { boxLabel: 'Battlehouse', name: 'frame_platform', inputValue: 'bh', labelWidth: 220, checked:false },
                      { boxLabel: 'Facebook', name: 'frame_platform', inputValue: 'fb', labelWidth: 220, checked:false },
                      { boxLabel: 'Kongregate', name: 'frame_platform', inputValue: 'kg', labelWidth: 220, checked:false },
                      { boxLabel: 'Mattermost', name: 'frame_platform', inputValue: 'mm', labelWidth: 220, checked:false }
                      ] }
                    ] },

                  { xtype: 'panel', id:'tech_panel', width:250,
                    title: 'Users Who Have Unlocked Units', bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    items: spin_techs, collapsible: true, collapsed: false, forceLayout: true },

                  { xtype: 'panel', id:'options_panel', width:250,
                    title: 'Options', bodyPadding: 4, margins: {bottom:4}, layout: { type: 'vbox', align: 'left', autoSize: true },
                    collapsible: true, collapsed: false, forceLayout: true,
                    items: [

                    { xtype: 'checkbox', fieldLabel: 'BIG Graphs', id:'client_big_graphs', name: 'client_big_graphs', labelWidth: 220, checked:false },
                    { xtype: 'checkbox', fieldLabel: 'Extrapolate Final Data Point', name: 'do_extrapolate', labelWidth: 220, checked:false },
                    { xtype: 'checkbox', fieldLabel: 'Graph Spend/Retention Curves (slow)', name: 'compute_spend_curve', labelWidth: 220, checked:false },
                    { xtype: 'checkbox', fieldLabel: 'Graph Ad Spend (slow)', name: 'compute_ads', labelWidth: 220, checked:false },
                    { xtype: 'checkbox', fieldLabel: 'Graph Player Progression (slower)', name: 'compute_progression', labelWidth: 220, checked:false },

                   { xtype: 'radiogroup', fieldLabel: 'Time Zone', name: 'utc_offset',
                     columns: 2, vertical: true, width:250, labelWidth: 65,
                     items: [{ boxLabel: 'UTC', name: 'utc_offset', inputValue: 0, checked:true },
                             { boxLabel: 'Pacific', name: 'utc_offset', inputValue: (spin_is_dst(new Date()) ? -7 : -8)*60*60 }, // note: bases DST decision on NOW
                             { boxLabel: 'Browser', name: 'utc_offset', inputValue: -(new Date()).getTimezoneOffset()*60 },
                            ]
                   },

                    { xtype: 'radiogroup', fieldLabel: 'Interval', name: 'sample_interval',
                    columns: 3, vertical: true, width:250, labelWidth: 65,
                    items: [{ boxLabel: 'Week', name: 'sample_interval', inputValue: 'week', },
                            { boxLabel: 'Day', name: 'sample_interval', inputValue: 'day', checked:true },
                            { boxLabel: 'Hour', name: 'sample_interval', inputValue: 'hour' },
                            { boxLabel: 'Minute', name: 'sample_interval', inputValue: 'minute' }
                            ]
                   },

                   { xtype: 'numberfield', fieldLabel: 'Trailing Window', width:240, name: 'interval_window', allowDecimals: false, minValue:1, maxValue: 1000 },

                   { xtype: 'radiogroup', fieldLabel: 'Funnel', name: 'conversion_rates',
                     columns: 2, vertical: true, width:250, labelWidth: 65,
                     items: [
                             { boxLabel: 'Raw', name: 'conversion_rates', inputValue: 0, checked:true },
                             { boxLabel: 'Conversions', name: 'conversion_rates', inputValue: 1, checked:false }
                            ]
                   },
                   { xtype: 'radiogroup', fieldLabel: 'Stages', name: 'funnel_stages',
                     columns: 2, vertical: true, width:250, labelWidth: 65,
                     items: [
                             { boxLabel: 'KPIs', name: 'funnel_stages', inputValue: 'skynet', checked:true },
                             { boxLabel: 'All', name: 'funnel_stages', inputValue: 'ALL', checked:false }
                            ]
                   },
                   { xtype: 'checkbox', fieldLabel: 'Show Correlation w/Paying', id:'client_show_pay_corr', name: 'client_show_pay_corr', labelWidth: 220, checked:false },

                   { xtype: 'radiogroup', fieldLabel: 'Sig Test', name: 'significance_test',
                     columns: 2, vertical: true, width:250, labelWidth: 65,
                     items: [{ boxLabel: 'G-test', name: 'significance_test', inputValue: 'g_test', checked:true },
                             { boxLabel: 'Chisquare', name: 'significance_test', inputValue: 'contingency_chisq' }
                            ]
                   },

                   //{ xtype: 'radiogroup', fieldLabel: 'CSV Format', name: 'csv_format',
                   //  columns: 2, vertical: true, width:250, labelWidth: 65,
                   //  items: [{ boxLabel: 'UserDB', name: 'csv_format', inputValue: 'userdb', checked:true },
                   //          { boxLabel: 'Time Series', name: 'csv_format', inputValue: 'time_series' }
                   //         ]
                   // },
                   { xtype: 'radiogroup', fieldLabel: 'Funnel CSV', name: 'client_funnel_csv_format', id:'client_funnel_csv_format',
                     columns: 2, vertical: true, width:250, labelWidth: 65,
                     items: [{ boxLabel: 'KPIs', name: 'client_funnel_csv_format', inputValue: 'kpis', checked:true },
                             { boxLabel: 'All', name: 'client_funnel_csv_format', inputValue: 'ALL' }
                            ]
                   },

                    { xtype: 'checkbox', fieldLabel: 'Local Debug Mode', id:'debug_local', name: 'debug_local', labelWidth: 220, checked:false }

                    ]
                    },

                    { xtype: 'textfield', fieldLabel: 'Manual Query', width:250, name: 'manual', value:'' },

                    ],
            timeout: 200000,
            buttons: [{
                text: 'Get Users As CSV',
                width: 130, height:40,
                handler: function() {
                // can't block UI because non-XHR request has no way to get response
                //if(spin_form_mutex) { return; }
                //spin_form_mutex = true;
                //if(!spin_form_mask) { spin_form_mask = new Ext.LoadMask(Ext.getBody(), {msg:"Creating CSV File..."}); }
                //spin_form_mask.show();

                    // force use of non-XHR request
                    Ext.getCmp('my_form').form.doAction('standardsubmit', {
                        url:location.href+'?output_mode=csv',
                        target:'_blank',
                        timeout: 200000,
                        success: function(f, a) { spin_form_mutex = false; spin_form_mask.hide(); console.log('OK'); },
                        failure: function(f, a) { spin_form_mutex = false; spin_form_mask.hide(); console.log('FAIL '+a.response); }
                    });
                 }
            },
            {
                text: 'Graph',
                width:130,height:40,
                handler: function() {
                            if(spin_form_mutex) { return; }
                            spin_form_mutex = true;
                            spin_form_mask.show();

                            //Ext.getCmp('status_text').setValue('Processing...');
                            Ext.getCmp('my_form').submit({
                                url:location.href+'?output_mode=graph',
                                timeout: 200000,
                                success: function(f, a) { spin_form_mutex = false; spin_form_mask.hide(); console.log('OK'); got_graphs(Ext.decode(a.response.responseText)); },
                                failure: function(f, a) { spin_form_mutex = false; spin_form_mask.hide(); console.log('FAIL'); console.log(a.response); }
                            });
                          }
            }]
            }),

          Ext.create('Ext.TabPanel', {
              region:'center', id:'vis_panel',
              items: [
          Ext.create('Ext.Panel', {
              region:'center',
              id: 'graph_panel',
              title: 'Graphs: Basic',
              scroll: 'vertical',
              autoScroll: true,
              layout: { type: 'vbox', padding: '10', align: 'left', pack: 'start', autoSize: true }, // align: 'stretch'
              items: []
              }),
         Ext.create('Ext.Panel', {
              region:'center',
              id: 'breakdown_panel',
              title: 'Graphs: Spend by Category',
              scroll: 'vertical',
              autoScroll: true,
              layout: { type: 'vbox', padding: '10', align: 'left', pack: 'start', autoSize: true }, // align: 'stretch'
              items: []
              }),
          Ext.create('Ext.Panel', {
              region:'center',
              id: 'progress_panel',
              title: 'Graphs: Progression',
              scroll: 'vertical',
              autoScroll: true,
              layout: { type: 'vbox', padding: '10', align: 'left', pack: 'start', autoSize: true }, // align: 'stretch'
              items: []
              }),
          Ext.create('Ext.Panel', {
          id: 'funnel_panel', title: 'Funnel',
          scroll: 'vertical', autoScroll: true,
          layout: { type: 'vbox', padding: '10', align: 'stretch', pack: 'start', autoSize: true }, // align: 'stretch'
          tbar: [{xtype: 'button', text: 'Run Query', cls:'x-btn-default-small', width: 200, handler: function() {
              spin_form_mask.show();
              Ext.getCmp('my_form').submit({
                  url:location.href+'?output_mode=funnel',
                  timeout: 200000,
                  failure: function(f, a) { spin_form_mask.hide(); console.log(a.response); },
                  success: function(f, a) { spin_form_mask.hide(); console.log('OK'); got_funnel(Ext.decode(a.response.responseText)); }
              });
              } }],
          items: []
          }),

          Ext.create('Ext.Panel', {
          id: 'units_panel', title: 'Units',
          scroll: 'vertical', autoScroll: true,
          layout: { type: 'vbox', padding: '10', align: 'stretch', pack: 'start', autoSize: true }, // align: 'stretch'
          tbar: [{xtype: 'button', text: 'Run Query', cls:'x-btn-default-small', width: 200, handler: function() {
              spin_form_mask.show();
              Ext.getCmp('my_form').submit({
                  url:location.href+'?output_mode=units',
                  timeout: 200000,
                  failure: function(f, a) { spin_form_mask.hide(); console.log(a.response); },
                  success: function(f, a) { spin_form_mask.hide(); console.log('OK'); got_units(Ext.decode(a.response.responseText)); }
              });
              } }],
          items: []
          }),


          Ext.create('Ext.Panel', {
          id: 'ads_panel', title: 'Ads',
          //scroll: 'vertical', autoScroll: true,
          //height: 800, bodyPadding: '10 10 0',
          layout: { type: 'vbox', padding: '20', pack: 'start', align: 'stretch' }, // align: 'stretch'
          items: [Ext.create('Ext.form.Panel', {
              title: 'Upload Ad Report', width: 400, bodyPadding: 10, frame:true,
              items: [
              {xtype:'box',isFormField:false,autoEl: {
              tag:'div', style: 'padding:10px;', children: [{tag:'img',src:'http://s3.amazonaws.com/'+public_s3_bucket+'/ad_data_upload2.jpg',width:'663',height:'384'}]
                       }},
                      {xtype: 'filefield', name: 'ad_csv_data', fieldLabel: 'Ad Report CSV File', width: 350, labelWidth: 150,
                       allowBlank: false, buttonText: 'Choose File'},
                      {id: 'ad_csv_status', xtype: 'displayfield', name: 'ad_csv_status', width:250, fieldLabel: 'Status', value: '' }

                      ],
              buttons: [{ text: 'Upload',
                          handler: function() {
                              var form = this.up('form').getForm();
                              if(form.isValid()) {
                                  form.submit({
                                      url:location.href+'?output_mode=upload_ad_csv',
                                      waitMsg:'Uploading...',
                                      failure: function(f, a) { console.log('FAILED!'); console.log(a.response); Ext.getCmp('ad_csv_status').setValue('Error! '+Ext.decode(a.response.responseText)['error']); },
                                      success: function(f, a) { console.log('UPLOAD OK'); console.log(a.response); Ext.getCmp('ad_csv_status').setValue('Upload OK!'); }
                                  });
                              }
                         }
              }]
              })]
          })
          ]}),

          Ext.create('Ext.Panel', {
              region:'south', preventHeader: true,
                 id: 'output_panel',
                 title: 'Status',
                 layout: { type: 'fit' },
                 items: {id: 'status_text', xtype: 'displayfield', anchor:'100% 100%', value: 'Ready'}
             })]
        });

        Ext.getCmp('abtest_panel').collapse();
        Ext.getCmp('regions_panel').collapse();
        //Ext.getCmp('currencies_panel').collapse();
        Ext.getCmp('frame_platform_panel').collapse();
        Ext.getCmp('age_group_panel').collapse();
        Ext.getCmp('browser_panel').collapse();
        Ext.getCmp('tech_panel').collapse();
        Ext.getCmp('options_panel').collapse();

        // AJAX RECEIVERS
        var display_error = function(retmsg) {
            Ext.Msg.alert('Error (send this to Dan):', '<tt>'+retmsg['error'].replace(/ /g, '&nbsp;').replace(/\\n/g, '<br />')+'</tt>');
        }

        // FUNNEL
        var got_funnel = function(retmsg) {

            if('error' in retmsg) {
                display_error(retmsg);
                return;
            }

            var SIGNIFICANCE = 0.05;
            var show_pay_corr = Ext.getCmp('client_show_pay_corr').getValue();

            console.log(retmsg);
            Ext.getCmp('status_text').setValue(retmsg['time_info']);
            var funnel_panel = Ext.getCmp('funnel_panel');
            funnel_panel.removeAll();
            funnel_panel.add(Ext.create('Ext.form.Display',{name:'Computed At',width:700,value:'Computed At: '+retmsg['compute_time']}));
            funnel_panel.add(Ext.create('Ext.form.Display',{name:'Source Data',width:700,value:'Using Data From: '+retmsg['upcache_time']}));
            funnel_panel.add(Ext.create('Ext.form.Display',{name:'Queries',width:700,value:'Queries: '+JSON.stringify(retmsg['queries'])}));

            funnel_panel.add(Ext.create('Ext.Button', {
                text: 'Get Funnel As CSV', scale: 'small', width:100, height:30, x:400, y:12,
                handler: (function (_funnel) { return function() {
                    var uriContent = 'data:text/plain,'+encodeURIComponent(funnel_to_csv(_funnel, Ext.getCmp('client_funnel_csv_format').getValue()['client_funnel_csv_format']));
                    window.open(uriContent, '_blank');
                }; })(retmsg['funnel'])
            }));

            var store = {fields:[], data:[]};
            store.fields.push({name:'stage_name'});
            // get cohort names

            // due to what seems like a bug in Ext.js that causes a syntax error on cohort names that start with "1." float-like strings,
            // we need to sanitize the cohort names here.
            var cohort_name = function(src) {
                while(src.indexOf('.') != -1) {
                  src = src.replace('.', '_');
                }
                return src;
            };

            for(var i = 0; i < retmsg['funnel'][0]['cohorts'].length; i++) {
                var cname = cohort_name(retmsg['funnel'][0]['cohorts'][i]['name']);
                store.fields.push({name:cname,type:'string'});
                store.fields.push({name:cname+'_conv',type:'string'});
                if(show_pay_corr) {
                    store.fields.push({name:cname+'_mcc_with_paying',type:'float'});
                    store.fields.push({name:cname+'_mcc_with_paying_p',type:'float'});
                }
            }
            if(retmsg['funnel'][0]['cohorts'].length == 2) {
                store.fields.push({name:'delta',type:'string'});
                store.fields.push({name:'odds_ratio',type:'string'});
                store.fields.push({name:'p',type:'float'});
            }
            // get data
            for(var i = 0; i < retmsg['funnel'].length; i++) {
                var stage = retmsg['funnel'][i];
                var rec = {stage_name: stage['stage']};
                for(var c = 0; c < stage['cohorts'].length; c++) {
                    var cohort = stage['cohorts'][c];
                    var cname = cohort_name(cohort['name']);
                    if(cohort['N'] < 1) {
                        rec[cname] = 'N=0';
                        rec[cname+'_conv'] = '-';
                    } else {
                        if('yes' in cohort) {
                            rec[cname] = cohort['yes'].toString()+' of N='+cohort['N'].toString();
                            rec[cname+'_conv'] = '<b>'+(100.0*cohort['yes']/cohort['N']).toFixed(1)+'%</b>';
                        } else if('value' in cohort) {
                            rec[cname] = 'N=' + cohort['N'].toString();
                            rec[cname+'_conv'] = '<b>$'+cohort['value'].toFixed(3)+'</b>';
                        }
                    }
                    if(show_pay_corr && 'mcc_with_paying' in cohort) {
                            rec[cname+'_mcc_with_paying'] = cohort['mcc_with_paying'];
                            rec[cname+'_mcc_with_paying_p'] = cohort['mcc_with_paying_p'];
                    }
                }
                if(stage['cohorts'].length == 2) {
                    var A = stage['cohorts'][0], B = stage['cohorts'][1];
                    if(A['N'] > 0 && B['N'] > 0 && A['yes'] > 0 && B['yes'] > 0) {
                        var s, odds;
                        if('yes' in A) {
                            var delta = B['yes']/B['N']-A['yes']/A['N'];
                            if(A['yes'] > 0) {
                                delta /= A['yes']/A['N'];
                            }
                            s = (delta>0?'+':'')+(100.0*delta).toFixed(1)+'%';
                            if(A['yes'] < A['N'] && B['yes'] < B['N']) {
                                odds = (B['yes']/(B['N']-B['yes']))/(A['yes']/(A['N']-A['yes']));
                                odds = odds.toFixed(2);
                             } else {
                                odds = '';
                             }
                        } else if('value' in A) {
                            var delta = B['value']-A['value'];
                            if(A['value'] > 0) {
                                delta /= A['value'];
                            }
                            s = (delta>0?'+':'')+(100.0*delta).toFixed(1)+'%';
                            odds = '';
                        }
                        if(stage['p'] > 0 && stage['p'] < SIGNIFICANCE) {
                            s = '<b>'+s+'</b>';
                            s = '<font color="#'+(delta>0?'009900':'DD0000')+'">'+s+'</font>'
                        } else {
                            s = '<font color="#808080">'+s+'</font>';
                        }
                        rec['delta'] = s;
                        rec['odds_ratio'] = odds;
                        rec['p'] = ('p' in stage ? stage['p'] : -1);
                    } else {
                        rec['delta'] = '';
                        rec['odds_ratio'] = '';
                        rec['p'] = -1;
                    }
                }
                store.data.push(rec);
            }
            // set up list view columns
            var columns = [{header:'Stage', dataIndex: 'stage_name', flex:1.5}];
            for(var i = 0; i < retmsg['funnel'][0]['cohorts'].length; i++) {
                var cname = cohort_name(retmsg['funnel'][0]['cohorts'][i]['name']);
                columns.push({header:cname, dataIndex: cname, flex:1});
                columns.push({header:'Conv', dataIndex: cname+'_conv', flex:0.5,
                               renderer: function(value) { return value; } });
                if(show_pay_corr) {
                    columns.push({header:'MCC', dataIndex: cname+'_mcc_with_paying', flex:0.5,
                                   renderer: function(value) { return value.toFixed(2); } });
                    columns.push({header:'MCCp<', dataIndex: cname+'_mcc_with_paying_p', flex:0.5});
                }
            }
            if(retmsg['funnel'][0]['cohorts'].length == 2) {
                columns.push({header:'\u0394', dataIndex: 'delta', flex:0.6});
                if(retmsg['conversion_rates']) {
                    columns.push({header:'Odds Ratio', dataIndex: 'odds_ratio', flex:0.6});
                }
                columns.push({header:'p<', dataIndex:'p', flex:0.6,
                               renderer: function(value) {
                                    if(value < 0) {
                                        return '';
                                    } else if(value > 1.1) {
                                        return '-';
                                    } if(value >= 0.0 && value < SIGNIFICANCE) {
                                        return '<font color="#FF0000"><b>'+value.toFixed(2)+'</b></font>';
                                    } else {
                                        return value.toFixed(2);
                                    }
                               } });
            }
            console.log(store); console.log(columns);
            funnel_panel.add(Ext.create('Ext.grid.Panel', {
                width:700, // flex:2,
                height:200 + 21 * retmsg['funnel'].length,
                resizable:true,
                store:Ext.create('Ext.data.JsonStore', store),
                columns:columns
            }));
            funnel_panel.doLayout();
        };

        // UNITS
        var got_units = function(retmsg) {
            console.log(retmsg);
            if('error' in retmsg) {
                display_error(retmsg);
                return;
            }

            Ext.getCmp('status_text').setValue(retmsg['time_info']);
            var units_panel = Ext.getCmp('units_panel');
            units_panel.removeAll();
            units_panel.add(Ext.create('Ext.form.Display',{name:'Computed At',width:700,value:'Computed At: '+JSON.stringify(retmsg['compute_time'])}));
            units_panel.add(Ext.create('Ext.form.Display',{name:'Queries',width:700,value:'Queries: '+JSON.stringify(retmsg['queries'])}));

            // get data
            for(var i = 0; i < retmsg['units'].length; i++) {
                var query = retmsg['units'][i]['query'];
                var units = retmsg['units'][i]['units'];

                var store = {fields:[], data:[]};
                store.fields.push({name:'unit_name'});
                var FIELDS = ['manufactured', 'manufactured_weighted',
                              'killed', 'killed_weighted', 'lost'];
                store.fields.push({name:'manufactured'});
                for(var f = 0; f < FIELDS.length; f++) {
                    store.fields.push({name:FIELDS[f]});
                }

                for(var u = 0; u < units.length; u++) {
                    var rec = {unit_name: units[u]['name']};
                    for(var f = 0; f < FIELDS.length; f++) {
                        rec[FIELDS[f]] = units[u][FIELDS[f]];
                    }
                    store.data.push(rec);
                }
                var json_store = Ext.create('Ext.data.JsonStore', store);

                var GRAPHS = [{'field': 'manufactured', 'ui_field': 'Units Manufactured\\n(unweighted)'},
                              {'field': 'manufactured_weighted', 'ui_field': 'Units Manufactured\\n(weighted by resource cost)'},
                              {'field': 'killed', 'ui_field': 'Units Killed By Me\\n(unweighted)'},
                              {'field': 'killed_weighted', 'ui_field': 'Units Killed By Me\\n(weighted by resource cost)'}
                              ];
                for(var g = 0; g < GRAPHS.length; g++) {
                    var GRAPH = GRAPHS[g];

                units_panel.add(Ext.create('Ext.chart.Chart', {
                    width:500, // flex:2,
                    height:500,
                    title: query, shadow:false, highlight: false,
                    legend: { position:'right', boxStroke: '', lineWidth: 2, labelFont: '12px bold sans-serif', itemSpacing: 0 \
                    },

                    resizable:true,
                    store:json_store,
                    series: [{type: 'pie',
                              field: GRAPH['field'],
                              showInLegend: true,
                              label: { field: 'unit_name' },
                              tips: {
            width: 140, height: 28,
            renderer: (function (_field) { return function(storeItem, item) {
                          this.setTitle(storeItem.get('unit_name')+': '+storeItem.get(_field).toFixed(1));
                          }; })(GRAPH['field'])
            }


                              }],

                    items: [{
                                type: 'text',
                                font: '16px bold',
                                text: query+': '+GRAPH['ui_field'], // title
                                x: 0, y: 18
                                }]

                    }));
                }
            }
            units_panel.doLayout();
        };



        // GRAPHS

        var got_graphs = function(retmsg) {
        console.log(retmsg);

        if('error' in retmsg) {
            display_error(retmsg);
            return;
        }

        var graph_panel = Ext.getCmp('graph_panel');
        var progress_panel = Ext.getCmp('progress_panel');
        var breakdown_panel = Ext.getCmp('breakdown_panel');
        var panels = {'graph': graph_panel, 'progress': progress_panel, 'breakdown': breakdown_panel};


        Ext.getCmp('status_text').setValue(retmsg['time_info']);

        for(var i in panels) {
            panels[i].removeAll();
            panels[i].add(Ext.create('Ext.form.Display',{name:'Computed At',width:700,value:'Computed At: '+retmsg['compute_time']}));
            panels[i].add(Ext.create('Ext.form.Display',{name:'Source Data',width:700,value:'Using Data From: '+retmsg['upcache_time']}));

            panels[i].add(Ext.create('Ext.form.Display',{name:'Queries',value:'Queries: '+JSON.stringify(retmsg['queries'])}));
        }

        var graph_colors = ['\#3333cc', '\#22aa22',  '\#cc33cc', '\#cc3333', '\#ffcc00',
                            '\#8033cc', '\#d86464', '\#e49595', '\#33cccc'];

        for(var gr = 0; gr < retmsg['graphs'].length; gr++) {
            var grdata = retmsg['graphs'][gr];
            var panel = panels[grdata['panel']];

            if(grdata['data'].length < 1) {
                // skip empty graph
                panel.add(Ext.create('Ext.form.Display',{name:'empty',value:'No data points for graph '+grdata['title']}));
                continue;
            }
            var store = Ext.create('Ext.data.JsonStore', grdata);

            // set Y axis max
            var ymax = -1, ymin = 0;
            for(var x = 0; x < grdata['data'].length; x++) {
                 var sample = grdata['data'][x];
                 for(var name in sample) {
                     if(grdata_field_name_is_valid(name)) {
                         var s = sample[name];
                         ymax = Math.max(ymax, s);
                         ymin = Math.min(ymin, s);
                     }
                 }
            }
            if(ymax < 0) {
                ymax = 1;
            }

            var range = ymax-ymin;
            var minClearance = Math.max(range*0.1, 0.01);

            var step = 0.01;
            var i = 1;
            while(range > step*10) {
                step *= ++i % 3 ? 2 : 2.5;
            }
            ymax = Math.ceil((ymax+minClearance)/step)*step;
            if(ymin != 0) {
                ymin = Math.floor((ymin-minClearance)/step)*step;
            }
            var steps = Math.round((ymax-ymin)/step);

            var formatters = {
            'number': function(value) { return value.toFixed(0); },
            'percent': function(value) { return (100*value).toFixed(0)+'%'; },
            'big_money': function(value) { return '$'+value.toFixed(0); },
            'little_money': function(value) { return '$'+value.toFixed(2); },
            'date': (function (_retmsg) { return function(value) {
                                      var d = new Date(value);
                                      // convert local time BACK into UTC time
                                      d = Ext.Date.add(d, Ext.Date.MINUTE, d.getTimezoneOffset());
                                      // and BACK with utc_offset
                                      d = Ext.Date.add(d, Ext.Date.SECOND, _retmsg['utc_offset']);
                                      return Ext.Date.format(d, "M d") + (_retmsg['utc_offset'] ? '*':''); }; })(retmsg)
            };
            var tip_renderer = function(name) {
                return function(storeItem, item) {
                    this.setTitle(storeItem.raw[name+'_tip']);
                };
            };

            var myseries = [];
            var my_ynames = [];
            for(var i = 1; i < grdata['fields'].length; i++) {
                my_ynames.push(grdata['fields'][i]['name']);
                myseries.push({ type: 'line', axis: ['left','bottom'],
                               xField:'xname', yField: grdata['fields'][i]['name'],
                               shadow: false, shadowAttributes: null,
                               highlight: {'stroke-width': 4}, // true,
                               style: {'stroke-width': 2, stroke: graph_colors[(i-1) % graph_colors.length]},
                               lineWidth: 2, fill: false,
                               selectionTolerance: 10,
                               showMarkers: true,
                               markerConfig: { type: 'circle', radius: 2,
                                               stroke: graph_colors[(i-1) % graph_colors.length],
                                               fill: graph_colors[(i-1) % graph_colors.length] },
                               title: grdata['fields'][i]['name'],
                               tips: {
                                   trackMouse: true,
                                   width: 350, height: 50,
                                   renderer: tip_renderer(grdata['fields'][i]['name'])
                                 }
                               });
            }

            var big = Ext.getCmp('client_big_graphs').getValue();

            // group the graph together with its controls
            var fset = Ext.create('Ext.form.FieldSet', {
                layout: 'absolute', width:800, height: (big ? 400 : 250)
            });

            fset.add(Ext.create('Ext.chart.Chart', {
            width:700, height: (big ? 400 : 250), insetPadding: 15, x:0, y:0,
            store:store, shadow: false, highlight: false,
            legend: { position:'right', boxStroke: '', lineWidth: 2, labelFont: '12px bold sans-serif', itemSpacing: 0 },
            axes: [ { title: '', type: 'Numeric', position: 'left',
                      fields: my_ynames,
                      minimum: ymin, maximum: ymax, step: step, steps: steps,
                      applyData: (function(_ymin, _ymax,_step,_steps) { return function() { return {from:_ymin,to:_ymax,step:_step,steps:_steps}; }; })(ymin,ymax,step,steps),
                      grid: true,
                      minorTickSteps: 0,
                      label: { renderer: formatters[grdata['y_format']] }
                      },
                    { title: '', type: grdata['fields'][0]['type'] == 'date' ? 'Time' : 'Numeric',
                    label: { renderer: formatters[grdata['x_format']] },
                    dateFormat: 'M d', minorTickSteps: 0,
                    fromDate: new Date(grdata['data'][0]['xname']*1000),
                    toDate: new Date(grdata['data'][grdata['data'].length-1]['xname']*1000),
                    position: 'bottom', fields: ['xname'] }
                    ],
            series: myseries,
            items: [{
              type: 'text',
              font: '16px bold',
              text: grdata['title'],
              x: 120, y: 18
            }]

        }));

        if(grdata['data'].length > 0) {
            fset.add(Ext.create('Ext.Button', {
                text: 'Get Graph As CSV', scale: 'small', width:100, height:20, x:645, y:(big?370:220),
                handler: (function (_grdata) { return function() {
                    var uriContent = 'data:text/plain,'+encodeURIComponent(grdata_to_csv(_grdata));
                    window.open(uriContent, '_blank');
                }; })(grdata)
            }));
        }

        panel.add(fset);

        }
        };
        });

        ''')
    def write_body(self, fd):
        return
        fd.write('<form id="myform" name="input" method="post">\n')
        fd.write('Country Tiers: ')
        for tier in ['1','2','3','4']:
            fd.write('<input type="checkbox" name="country_tier" value="%s" %s />%s\n' % (tier, 'checked="checked"' if tier in self.args.get('country_tier',[]) else '', tier))

        fd.write('<br>Campaign: ')
        fd.write('<select name="acquisition_campaign" multiple="multiple" size="15">\n')
        for camp in self.campaign_list:
            fd.write('<option value="%s" %s>%s</option>\n' % (camp, 'selected="selected"' if camp in self.args.get('acquisition_campaign',[]) else '', camp))
        fd.write('</select>\n')

        fd.write('Start Date: <input type="text" id="start_date_picker"><input type="hidden" name="start_date" id="start_date">\n')
        fd.write('End Date: <input type="text" id="end_date_picker"><input type="hidden" name="end_date" id="end_date">\n')

        fd.write('<center>\n')
        fd.write('<button type="button" onclick="myform_submit_ui()" style="width: 100px; font-size: 24px;">GO</button>\n')
        fd.write('<button type="button" onclick="myform_submit_csv()" style="width: 100px; ">Do not Click</button>\n') # CSV output
        fd.write('<input type="hidden" name="output_mode" id="output_mode" value="ui">\n')
        fd.write('<input type="checkbox" name="skip" value="1" %s />Skip Metrics\n' % ('checked="checked"' if 'skip' in self.args else ''))
        fd.write('</center>\n')
        fd.write('</form>\n')

class DataSeries (object):
    def __init__(self, samples, x_format, y_format, N_samples = None, SD_samples = None, name = None):
        self.name = name
        self.samples = samples
        self.x_format = x_format
        self.y_format = y_format
        self.N_samples = N_samples
        self.SD_samples = SD_samples

class GoogleCharts (PageContent):
    def write_head(self, fd):
        fd.write('<script type="text/javascript" src="https://www.google.com/jsapi"></script>\n')
    def write_head_script(self, fd):
        fd.write('''
          // Load the Visualization API
          google.load('visualization', '1.0', {'packages':['corechart']});

          // Set a callback to run when the Google Visualization API is loaded.
          var SPIN_GoogleCharts_init = [];
          google.setOnLoadCallback(drawCharts);
          function drawCharts() {
             for(var i = 0; i < SPIN_GoogleCharts_init.length; i++) {
                 SPIN_GoogleCharts_init[i]();
             }
          };''')

class Chart (PageContent):
    counter = 0

    # series = list of DataSeries objects
    def __init__(self, title, series, window = 1, extrap = 'none', bounds = [-1,-1], N_min = 1, panel = 'graph', utc_offset = 0):
        self.div_name = 'chart_div%d' % Chart.counter
        Chart.counter += 1
        self.title = title
        self.series = [] # added below
        self.window = window
        self.extrap = extrap
        self.N_min = N_min
        self.panel = panel
        self.utc_offset = utc_offset

        # create a union of all the X values from all series (where sample[X] > 0 and N[X] >= N_min)
        # so Ext JS can plot them all on the same graph
        temp = set()
        for data in series:
            series_points = 0
            for key, val in data.samples.iteritems():
                #if val == 0: continue
                if data.N_samples and data.N_samples[key] < self.N_min: continue
                if bounds[0] > 0 and key < bounds[0]: continue
                if bounds[1] > 0 and key >= bounds[1]: continue
                temp.add(key)
                series_points += 1
            if 1 or series_points >= 2:
                self.series.append(data)

        self.x_vals = sorted(list(temp))


    def get_json(self):
        EXT_FORMATS = {
            'date': 'date',
            'number': 'float'
            }
        VALUE_FORMATS = {
            'big_money': '$%.2f',
            'little_money': '$%.3f',
            'number': '%g',
            'percent': '%.1f%%'
            }

        # note: to omit a data point, put 'false' as the Y value in JSON
        ret = {'fields': [{'name':'xname', 'type':EXT_FORMATS[self.series[0].x_format], 'dateFormat':'timestamp'}] + \
                         [{'name':data.name,'type':'auto'} for data in self.series] }

        ret['title'] = self.title
        ret['x_format'] = self.series[0].x_format
        ret['y_format'] = self.series[0].y_format
        ret['panel'] = self.panel

        rdata = []
        n_nonzero = 0
        nonzero_series = set()

        if 1:
            last_point = len(self.x_vals)
            if self.extrap == 'omit':
                last_point -= 1

            for j in xrange(last_point):

                samp = {}

                if self.series[0].x_format == 'date':
                    # note: JavaScript uses 0-11 for months!

                    # send raw UTC timestamp
                    samp['xname'] = self.x_vals[j]

                    # build tooltip
                    # kind of wrong, what we are trying to do is display the LOCAL time at this timestamp
                    gmt = time.gmtime(self.x_vals[j] + self.utc_offset)
                    month, day, hour, min = gmt.tm_mon, gmt.tm_mday, gmt.tm_hour, gmt.tm_min
                    tooltip = '%s %d %02d:%02d%s' % (MONTH_NAMES[month-1], day, hour, min, '*' if self.utc_offset != 0 else '')

                    samp['xname_human_local'] = time.strftime('%m/%d/%Y', gmt)

                elif self.series[0].x_format == 'number':
                    tooltip = '%g' % self.x_vals[j]
                    samp['xname'] = self.x_vals[j]
                else:
                    raise Exception('unhandled x_format')

                for data in self.series:
                    n_total = 0
                    value = 0
                    N = 0

                    for k in range(self.window):
                        if j-k < 0:
                            continue
                        if self.x_vals[j-k] in data.samples:
                            n_total += 1
                            value += data.samples.get(self.x_vals[j-k], 0)
                            if data.N_samples:
                                N += data.N_samples.get(self.x_vals[j-k], 0)

                    if n_total > 0:
                        value /= float(n_total)
                        N /= float(n_total)

                    if n_total == 0 or (data.N_samples and N < self.N_min):
                        # omit data points where N is insufficient
                        samp[data.name] = False
                        samp[data.name+'_tip'] = data.name +': NO DATA'
                        continue

                    if value != 0:
                        n_nonzero += 1
                    elif n_nonzero == 0:
                        # omit data points before starting of nonzero sample values
                        samp[data.name] = False
                        samp[data.name+'_tip'] = data.name +': NO DATA'
                        continue

                    warning = ''

                    if j >= (last_point-1):
                        if self.extrap == 'time':
                            warning = '(PROJECTED) '

                    str_value = VALUE_FORMATS[data.y_format] % (100.0*value if data.y_format == 'percent' else value)

                    samp[data.name] = value
                    samp[data.name+'_tip'] = data.name + ' ' + warning + tooltip + ': ' + str_value + ((' (N=%d)' % N) if data.N_samples else '')
                    if data.SD_samples:
                        samp[data.name+'_tip'] += ' (SD='+VALUE_FORMATS[data.y_format]%data.SD_samples.get(self.x_vals[j],0)+')'
                    nonzero_series.add(data.name)
                rdata.append(samp)

        # filter out series that do not contribute to the graph
        for data in self.series:
            if data.name not in nonzero_series:
                for entry in ret['fields']:
                    if entry['name'] == data.name:
                        ret['fields'].remove(entry)
                for sample in rdata:
                    if data.name in sample: del sample[data.name]
                    if data.name+'_tip' in sample: del sample[data.name+'_tip']

        ret['data'] = rdata
        return ret

    def write_body(self, fd):
        fd.write('<div id="%s"></div>\n' % self.div_name)

    def write_head_script(self, fd):

        JS_FORMATS = {
            'date': 'Date',
            'number': 'number'
            }
        VALUE_FORMATS = {
            'big_money': '$%.2f',
            'little_money': '$%.3f',
            'number': '%g',
            'percent': '%.1f%%'
            }
        ICU_FORMATS = {
            'big_money': '\u00A4 #,##0',
            'little_money': '\u00A4 #,##0.00', # shows cents
            'number': '#,##0',
            'percent': '##0 %'
            }

        ret = ['''
        SPIN_GoogleCharts_init.push(function() {
        var data = new google.visualization.DataTable();
        data.addColumn('%s', '%s');
        data.addColumn('number', 'Val');
        data.addColumn({type:'string', role:'tooltip'});
        data.addColumn({type:'boolean', role:'certainty'});
        data.addRows([''' % (self.data.x_format, JS_FORMATS[self.data.x_format])]

        n_nonzero = 0

        last_point = len(self.data.x)
        if self.extrap == 'omit':
            last_point -= 1

        for j in xrange(last_point):
            n_total = 0
            value = 0
            N = 0

            for k in range(self.window):
                if j-k < 0:
                    continue
                n_total += 1
                data = self.data.y[j-k]
                value += data
                if self.data.N:
                    N += self.data.N[j-k]

            value /= float(n_total)
            N /= float(n_total)

            if self.data.N and N == 0:
                # omit data points where N=0
                continue

            if value != 0:
                n_nonzero += 1
            elif n_nonzero == 0:
                continue

            certainty = 'true'

            if j >= (len(self.data.x)-1):
                if self.extrap == 'time':
                    raise 'unhandled extrapolation'
                    certainty = 'false'
                    duration = data['end_time']-data['time']
                    value *= (24*60*60)/float(duration)

            str_value = VALUE_FORMATS[self.data.y_format] % (100.0*value if self.data.y_format == 'percent' else value)

            if self.data.x_format == 'date':
                # note: JavaScript uses 0-11 for months!
                year, month, day = self.data.x[j]
                js_x_value = 'new Date(%d, %d, %d)' % (year, month-1, day)
                tooltip = '%s %d' % (MONTH_NAMES[month-1], day)
            elif self.data.x_format == 'number':
                tooltip = '%g' % self.data.x[j]
                js_x_value = '%g' % self.data.x[j]
            else:
                raise 'unhandled x_format'
            tooltip += ': %s' % str_value
            if self.data.N:
                tooltip += ' (N=%d)' % N

            str = '[%s, %g, "%s", %s]' % (js_x_value, value, tooltip, certainty)
            if j != len(self.data.x)-1:
                str += ','
            ret.append(str)

        if n_nonzero < 2:
            sys.stderr.write('not enough data yet for %s\n' % (self.title))
            # empty chart


        width = 600
        height = 200

        ret.append(']);')
        ret.append("var options = {};")
        ret.append("options['legend'] = 'none';")
        ret.append("options['title'] = '"+self.title+"';")
        ret.append("options['width'] = %d;" % width)
        ret.append("options['height'] = %d;" % height)
        ret.append("options['vAxis']= {'format':'%s'};" % ICU_FORMATS[self.data.y_format])
        ret.append('''
        // Instantiate and draw our chart, passing in some options.
        var chart = new google.visualization.LineChart(document.getElementById('%s'));
        chart.draw(data, options);
        });
        ''' % self.div_name)
        fd.write(string.join(ret, '\n'))

class Page (object):
    def __init__(self):
        self.content = []
    def add(self, c):
        self.content.append(c)
    def write_head(self, fd):
        for c in self.content:
            c.write_head(fd)

        fd.write('<script type="text/javascript">\n')
        for c in self.content:
            c.write_head_script(fd)
        fd.write('</script>\n')

    def write_body(self, fd):
        for c in self.content:
            c.write_body(fd)
