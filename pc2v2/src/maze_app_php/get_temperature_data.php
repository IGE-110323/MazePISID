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
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT Temperatura as temperatura, IDTemperatura as idtemperatura 
        FROM Temperatura 
        JOIN Simulacao s ON s.IDSimulacao = Temperatura.IDSimulacao 
        WHERE s.Status = 1 
        ORDER BY IDTemperatura ASC";
$result = $conn->query($sql);

if ($result) {
    $tempData = array();
    while ($row = $result->fetch_assoc()) {
        $tempData[] = $row;
    }
    $response['success'] = true;
    $response['data']    = $tempData;
    $response['message'] = 'Dados de temperatura carregados com sucesso.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}

$conn->close();
echo json_encode($response);
?>