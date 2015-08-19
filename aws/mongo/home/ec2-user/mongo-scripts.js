// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// download a full server backup
export AWS="/home/ec2-user/aws --secrets-file=/home/ec2-user/XXX-awssecret"
for F in `$AWS ls -1  spinpunch-backups/marsfrontier2-player-data-20140205/mongo`; do $AWS get --progress spinpunch-backups/$F `basename $F`; done
for F in *.cpio.gz; do gunzip -c $F | cpio -ivd; done
rm -rf admin

// restore the backup
/usr/local/mongodb/bin/mongorestore -u root -p `cat /home/ec2-user/.ssh/mf2prod-mongo-root-password` --authenticationDatabase admin .

//////////////////////////////
// 2014 Feb 2 TR database migration

use admin;
// add mf2_ prefix to core tables
db.runCommand({renameCollection: 'mf2prod.abtests', to: 'mf2prod.mf2_abtests'});
db.runCommand({renameCollection: 'mf2prod.facebook_id_map', to: 'mf2prod.mf2_facebook_id_map'});
// split big global tables to their own dbs
db.runCommand({renameCollection: 'mf2prod.auth_csrf_state', to: 'mf2prod_auth.auth_csrf_state'});
db.runCommand({renameCollection: 'mf2prod.player_cache', to: 'mf2prod_player_cache.mf2_player_cache'});
db.runCommand({renameCollection: 'mf2prod.player_scores', to: 'mf2prod_player_scores.mf2_player_scores'});
db.runCommand({renameCollection: 'mf2prod.message_table', to: 'mf2prod_messages.mf2_message_table'});

// split alliance tables to their own db
['alliance_invites','alliance_roles','alliance_join_requests','alliance_members','alliances_roles','alliance_score_cache','alliance_turf','alliances','unit_donation_requests'].forEach(function(x) {db.runCommand({renameCollection: 'mf2prod.'+x, to: 'mf2prod_alliances.mf2_'+x}); });

// split region-specific tables into one database per region
var old_db = 'mf2prod_regions';
var ls2 = db.getSiblingDB(old_db).getCollectionNames();
for(var i = 0; i < ls2.length; i++) {
    var a = ls2[i];
    var new_db = null, new_coll = null;
    if(a.indexOf("mf2_region_") == 0) {
        if(a.indexOf("mf2_region_ladder") == 0) {
            new_db = "mf2prod_region_ladder"; // put all ladder regions in one DB
        } else {
        new_db = "mf2prod_"+a.split("_").slice(1,3).join("_");
        }
    new_coll = a;
    }
    if(new_db && new_coll) {
    db.runCommand({renameCollection: old_db+"."+a, to: new_db+"."+new_coll});
    }
}
db.getSiblingDB(old_db).dropDatabase();

//////////////////////////////////

// run .repairDatabase() on all databases
db.adminCommand('listDatabases')['databases'].forEach(function(x) {
    print('repairing '+x['name']+'...');
    db.getSiblingDB(x['name']).repairDatabase();
});

// run .validate() on all collections
db.adminCommand('listDatabases')['databases'].forEach(function(dbdata) {
    var this_db = db.getSiblingDB(dbdata['name']);
    this_db.getCollectionNames().forEach(function(cname) {
        if(cname.indexOf('_region_') == -1) { continue; } // skip non-region collections
        print('validating '+dbdata['name']+'.'+cname+'...');
        result = this_db.getCollection(cname).validate({full:true});
        if(result['errors'] && result['errors'].length > 0) {
            print('ERRORS: ');
            printjson(result['errors']);
        }
    });
});

// print size of all DB collections
db.getCollectionNames().forEach(function (x) { var stats = db.getCollection(x).stats(); printjson(stats['ns']+': '+(stats['size']/(1024*1024)).toFixed(1) + ' MB, '+(stats['storageSize']/(1024*1024)).toFixed(1)+' MB on disk'); })
