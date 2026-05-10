<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '', 'data' => array());

$username = $_REQUEST['username'] ?? '';
$password = $_REQUEST['password'] ?? '';
$database = $_REQUEST['database'] ?? '';

if (empty($username) || empty($password) || empty($database)) {
    $response['message'] = 'Preencha todos os campos.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli('localhost', $username, $password, $database, 3307);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT ID AS idtemperatura, value AS temperatura FROM Temperature ORDER BY ID ASC";
$result = $conn->query($sql);

if ($result) {
    $tempData = array();
    while ($row = $result->fetch_assoc()) {
        $tempData[] = $row;
    }
    $response['success'] = true;
    $response['data'] = $tempData;
    $response['message'] = 'Dados de temperatura carregados com sucesso.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}

$conn->close();
echo json_encode($response);
?>