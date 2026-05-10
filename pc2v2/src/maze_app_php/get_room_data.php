<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '', 'data' => array());

$database = $_REQUEST['database'] ?? '';

if (empty($database)) {
    $response['message'] = 'Preencha todos os campos.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli(DB_HOST, DB_USER_ANDROID, DB_PASS_ANDROID, $database);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão MySQL: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT o.Sala, o.NumeroMarsamisEven, o.NumeroMarsamisOdd 
        FROM OcupacaoLabirinto o 
        JOIN Simulacao s ON s.IDSimulacao = o.IDJogo 
        WHERE s.Status = 1 
        ORDER BY o.Sala ASC";
$result = $conn->query($sql);

if ($result) {
    $rooms = array();
    while ($row = $result->fetch_assoc()) {
        $rooms[] = $row;
    }
    $response['success'] = true;
    $response['data']    = $rooms;
    $response['message'] = 'Dados dos corredores carregados com sucesso.';
} else {
    $response['message'] = 'Erro ao executar consulta: ' . $conn->error;
}

$conn->close();
echo json_encode($response);
?>