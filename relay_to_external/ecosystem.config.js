module.exports = {
	apps: [
		{
			name: "glove_beetle_server",
			script: "python -u glove_beetle_server.py",
			instances: 2,
			increment_var: "PLAYER_ID",
			env: {
				PLAYER_ID: 1,
			},
		},
		{
			name: "leg_beetle_server",
			script: "python -u leg_beetle_server.py",
			instances: 2,
			increment_var: "PLAYER_ID",
			env: {
				PLAYER_ID: 1,
			},
		},
		{
			name: "vest_beetle_server",
			script: "python -u vest_beetle_server.py",
			instances: 2,
			increment_var: "PLAYER_ID",
			env: {
				PLAYER_ID: 1,
			},
		},
		{
			name: "view_predictions",
			script: "python -u view_predictions.py",
		},
	],
};
