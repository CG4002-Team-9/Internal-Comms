module.exports = {
	apps: [
		{
			name: "imu_to_csv",
			script: "python -u collect_imu_to_csv.py",
			instances: 2,
			increment_var: "PLAYER_ID",
			env: {
				PLAYER_ID: 1,
			},
		},
	],
};
