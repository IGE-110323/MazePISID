<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '', 'data' => array());

$database = $_REQUEST['database'] ?? '';
if (empty($database)) {
    $response['message'] = 'Database em falta.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli('localhost', 'root', 'admin', $database, 3307);
if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT ID_room AS Sala, oddCount AS NumeroMarsamisOdd, evenCount AS NumeroMarsamisEven 
        FROM RoomSimulation 
        WHERE ID_simulation = (SELECT ID FROM Simulation WHERE status = 'active' ORDER BY ID DESC LIMIT 1)";
$result = $conn->query($sql);
if ($result) {
    $rooms = array();
    while ($row = $result->fetch_assoc()) {
        $rooms[] = $row;
    }
    $response['success'] = true;
    $response['data'] = $rooms;
    $response['message'] = 'Dados das salas carregados com sucesso.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}
$conn->close();
echo json_encode($response);
?>