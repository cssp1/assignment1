// create gametest user inside the gametest DB
db.createUser({user:'gametest',pwd:'gametest',roles:[{role:'readWrite',db:'gametest'}]})
