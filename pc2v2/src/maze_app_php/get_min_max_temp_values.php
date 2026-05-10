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

$conn = new mysqli(DB_HOST, DB_USER_ANDROID, DB_PASS_ANDROID, $database);

if ($conn->connect_error) {
    $response['message'] = "Erro de ligação: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT m.NormalTemperature - m.TempLowToleration as minimo, 
               m.NormalTemperature + m.TempHighToleration as maximo 
        FROM Maze m 
        JOIN SimulationConfig sc ON sc.IDMaze = m.IDMaze 
        LIMIT 1";
$result = $conn->query($sql);

if ($result && $row = $result->fetch_assoc()) {
    $response['success'] = true;
    $response['data']    = array(
        "minimo" => (float)$row['minimo'],
        "maximo" => (float)$row['maximo']
    );
} else {
    $response['message'] = "Não foram encontrados limites na tabela.";
}

$conn->close();
echo json_encode($response);
?>