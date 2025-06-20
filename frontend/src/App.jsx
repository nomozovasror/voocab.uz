import './App.css'
import axios from "axios";
import {useEffect, useState} from "react";

function App() {

    const [hello, setHello] = useState(null)

    useEffect(() => {
        axios.get("http://127.0.0.1:8000").then(
        response => {
            setHello(response.data.message)
            console.log(response.data.message)
        }
    )
    }, []);

  return (
    <>
        <h1>{hello}</h1>
    </>
  )
}

export default App
