<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '', 'data' => null);

$database = $_REQUEST['database'] ?? '';

if (empty($database)) {
    $response['message'] = 'Preencha todos os campos.';
    echo json_encode($response);
    exit;
}

// Requer admin_bd — acede a ServiceHealth e CommandQueue
$conn = new mysqli(DB_HOST, DB_USER_ADMIN, DB_PASS_ADMIN, $database);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT 
    ServiceName,
    PCLocation,
    LastHeartbeat,
    Status,
    TIMESTAMPDIFF(SECOND, LastHeartbeat, UTC_TIMESTAMP()) as seconds_ago,
    CASE 
        WHEN LastHeartbeat IS NULL THEN 'unknown'
        WHEN TIMESTAMPDIFF(SECOND, LastHeartbeat, UTC_TIMESTAMP()) < 10 THEN 'online'
        ELSE 'offline'
    END as computed_status
FROM ServiceHealth
ORDER BY PCLocation, ServiceName";

$result = $conn->query($sql);
$services   = array();
$all_online = true;

while ($row = $result->fetch_assoc()) {
    if ($row['computed_status'] !== 'online'
        && $row['ServiceName'] !== 'mazerun') {
        $all_online = false;
    }
    $services[] = $row;
}

$sim_result = $conn->query("
    SELECT s.IDSimulacao, s.Status, s.DataHoraInicio, t.PlayerNumber
    FROM Simulacao s
    JOIN Team t ON t.IDTeam = s.IDTeam
    WHERE s.Status = 1
    ORDER BY s.IDSimulacao DESC
    LIMIT 1
");
$active_sim = $sim_result->fetch_assoc();

$cmd_result = $conn->query("
    SELECT COUNT(*) as pending
    FROM CommandQueue
    WHERE Status = 0
");
$pending = $cmd_result->fetch_assoc();

$response['success'] = true;
$response['message'] = $all_online ? 'Todos os serviços online.' : 'Atenção — alguns serviços offline.';
$response['data']    = array(
    'services'          => $services,
    'all_online'        => $all_online,
    'active_simulation' => $active_sim,
    'pending_commands'  => (int)$pending['pending']
);

$conn->close();
echo json_encode($response);
?>