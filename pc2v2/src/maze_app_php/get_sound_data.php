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

$sql = "SELECT Som as som, IDSom as idsom 
        FROM Som 
        JOIN Simulacao s ON s.IDSimulacao = Som.IDSimulacao 
        WHERE s.Status = 1 
        ORDER BY IDSom ASC";
$result = $conn->query($sql);

if ($result) {
    $soundData = array();
    while ($row = $result->fetch_assoc()) {
        $soundData[] = $row;
    }
    $response['success'] = true;
    $response['data']    = $soundData;
    $response['message'] = 'Dados de som carregados com sucesso.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}

$conn->close();
echo json_encode($response);
?>