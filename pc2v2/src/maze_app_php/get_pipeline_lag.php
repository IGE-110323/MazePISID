<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '', 'data' => null);

$database     = $_REQUEST['database']     ?? '';
$id_simulacao = (int)($_REQUEST['id_simulacao'] ?? 0);

if (empty($database) || $id_simulacao <= 0) {
    $response['message'] = 'Database ou id_simulacao em falta.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli(DB_HOST, DB_USER_JOGO, DB_PASS_JOGO, $database);
if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "
    SELECT 'movements' as colecao,
        AVG(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000) as lag_medio_ms,
        MAX(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000) as lag_max_ms,
        MIN(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000) as lag_min_ms,
        COUNT(*) as total
    FROM MedicoesPassagens WHERE IDSimulacao = ?
    UNION ALL
    SELECT 'temperature',
        AVG(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000),
        MAX(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000),
        MIN(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000),
        COUNT(*)
    FROM Temperatura WHERE IDSimulacao = ?
    UNION ALL
    SELECT 'sound',
        AVG(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000),
        MAX(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000),
        MIN(TIMESTAMPDIFF(MICROSECOND, Hora, HoraEscrita)/1000),
        COUNT(*)
    FROM Som WHERE IDSimulacao = ?
";

$stmt = $conn->prepare($sql);
$stmt->bind_param("iii", $id_simulacao, $id_simulacao, $id_simulacao);
$stmt->execute();
$result = $stmt->get_result();
$data   = [];
while ($row = $result->fetch_assoc()) $data[] = $row;
$stmt->close();
$conn->close();

$response['success'] = true;
$response['data']    = $data;
echo json_encode($response);
?>